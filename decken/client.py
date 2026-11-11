from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

DEFAULT_BASE_URL = "https://api.decken.ai"

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class DeckenError(RuntimeError):
    def __init__(self, message: str, status_code: int = 0, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _is_loopback(hostname: Optional[str]) -> bool:
    if not hostname:
        return False
    h = hostname.lower()
    return h in ("localhost", "127.0.0.1", "::1") or h.endswith(".localhost")


def validate_base_url(base_url: str, has_api_key: bool, allow_insecure_localhost: bool = True) -> str:
    parsed = urllib.parse.urlparse(base_url.strip())
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise DeckenError(f"Invalid Decken base_url: {base_url}")
    if parsed.scheme != "https":
        if parsed.scheme == "http" and allow_insecure_localhost and _is_loopback(parsed.hostname):
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        if has_api_key:
            raise DeckenError(
                f"Refusing insecure non-HTTPS base_url ({base_url}) when transmitting API credentials."
            )
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"


def normalize_artifact_payload(raw: Any, field_name: str = "artifact") -> Any:
    if raw is None:
        return None
    if isinstance(raw, Path):
        raw = str(raw)
    if isinstance(raw, str):
        trimmed = raw.strip()
        if not trimmed:
            return None
        if trimmed.startswith("https://") or trimmed.startswith("data:"):
            return trimmed
        if trimmed.startswith("http://"):
            raise DeckenError(f"`{field_name}` URL must use HTTPS (https://...).")
        p = Path(trimmed)
        ext = p.suffix.lower()
        if ext in (".pptx", ".potx"):
            mime = PPTX_MIME
        else:
            guessed, _ = mimetypes.guess_type(p.name)
            mime = guessed or "application/octet-stream"
        encoded = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    if isinstance(raw, dict):
        if raw.get("url"):
            u = str(raw["url"]).strip()
            if not u.startswith("https://"):
                raise DeckenError(f"`{field_name}.url` must use HTTPS (https://...).")
            return {**({"kind": raw["kind"]} if "kind" in raw else {}), "url": u}
        if raw.get("dataUrl"):
            return {**({"kind": raw["kind"]} if "kind" in raw else {}), "dataUrl": str(raw["dataUrl"]).strip()}
        if raw.get("path"):
            data_url = normalize_artifact_payload(raw["path"], field_name)
            return {**({"kind": raw["kind"]} if "kind" in raw else {}), "dataUrl": data_url}
    raise DeckenError(f"Unsupported `{field_name}` input.")


def normalize_image_data_url(
    *,
    image_path: Optional[Union[str, Path]] = None,
    image_bytes: Optional[bytes] = None,
    image_data_url: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> str:
    if image_data_url and image_data_url.strip():
        raw = image_data_url.strip()
        return raw if raw.startswith("data:image/") else f"data:image/png;base64,{raw}"
    if image_bytes is not None:
        mime = mime_type or "image/png"
        return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    if image_path is not None:
        p = Path(image_path)
        guessed, _ = mimetypes.guess_type(p.name)
        mime = mime_type or guessed or "image/png"
        encoded = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    raise DeckenError("Slide input requires `image_path`, `image_bytes`, or `image_data_url`.")


class DeckenClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 180.0,
        allow_insecure_localhost: bool = True,
    ) -> None:
        resolved_key = (
            api_key
            if api_key is not None
            else os.environ.get("DECKEN_API_KEY") or os.environ.get("DECKEN_API_TOKEN") or ""
        ).strip()
        self.api_key = resolved_key
        raw_base = (base_url or os.environ.get("DECKEN_BASE_URL") or DEFAULT_BASE_URL).strip()
        self.base_url = validate_base_url(raw_base, bool(self.api_key), allow_insecure_localhost)
        self.timeout = timeout

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if extra:
            headers.update(extra)
        return headers

    def _request_json(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = self._headers({"Content-Type": "application/json"} if payload is not None else None)
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            raw_err = err.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw_err)
                msg = parsed.get("error") or f"Decken API HTTP {err.code}"
            except Exception:
                parsed = raw_err
                msg = f"Decken API HTTP {err.code}: {raw_err}"
            raise DeckenError(msg, err.code, parsed) from err

    def _request_bytes(self, path: str) -> bytes:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            raw_err = err.read().decode("utf-8", errors="replace")
            raise DeckenError(f"Binary download failed ({err.code}): {raw_err}", err.code, raw_err) from err

    def get_capabilities(self) -> Dict[str, Any]:
        return self._request_json("GET", "/v1/capabilities")

    def get_openapi_spec(self) -> Dict[str, Any]:
        return self._request_json("GET", "/v1/openapi.json")

    def get_agent_manifest(self) -> Dict[str, Any]:
        return self._request_json("GET", "/.well-known/agent.json")

    def list_jobs(self) -> Dict[str, Any]:
        return self._request_json("GET", "/v1/jobs")

    def get_job(self, job_id: str, include_base64: bool = False) -> Dict[str, Any]:
        suffix = "?includeBase64=1" if include_base64 else ""
        return self._request_json("GET", f"/v1/jobs/{urllib.parse.quote(job_id)}{suffix}")

    def download_pptx(self, job_id_or_url: str) -> bytes:
        path = (
            job_id_or_url
            if job_id_or_url.startswith("/") or job_id_or_url.startswith("http")
            else f"/v1/jobs/{urllib.parse.quote(job_id_or_url)}/pptx"
        )
        return self._request_bytes(path)

    def download_slide_preview(self, job_id: str, slide_id: str) -> bytes:
        return self._request_bytes(
            f"/v1/jobs/{urllib.parse.quote(job_id)}/slides/{urllib.parse.quote(slide_id)}/preview.png"
        )

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval: float = 2.0,
        max_wait: float = 600.0,
        include_base64: bool = False,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            job = self.get_job(job_id, include_base64=include_base64)
            if on_progress:
                on_progress(job)
            if job.get("status") == "completed":
                return job
            if job.get("status") == "failed":
                raise DeckenError(job.get("error") or f"Job {job_id} failed", 500, job)
            time.sleep(poll_interval)
        raise DeckenError(f"Timed out waiting for job {job_id}", 408)

    def generate(
        self,
        *,
        outline: Optional[Union[str, Sequence[Dict[str, Any]]]] = None,
        prompt: Optional[str] = None,
        reference: Optional[Union[str, Path, Dict[str, Any]]] = None,
        source: Optional[Union[str, Path, Dict[str, Any], Sequence[Any]]] = None,
        deck_title: Optional[str] = None,
        mode: str = "sync",
        engine_mode: str = "vlm",
        model_id: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        include_pptx_base64: Optional[bool] = None,
        output_path: Optional[Union[str, Path]] = None,
        wait: bool = True,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        norm_ref = normalize_artifact_payload(reference, "reference")
        if isinstance(source, (list, tuple)):
            norm_src: Any = [normalize_artifact_payload(s, f"source[{i}]") for i, s in enumerate(source)]
        else:
            norm_src = normalize_artifact_payload(source, "source")

        if norm_src is None and outline is None and not prompt:
            raise DeckenError("`generate` requires `outline` / `prompt` (Scenarios 1 & 2) or `source` (Scenario 3).")

        payload: Dict[str, Any] = {
            "mode": mode,
            "engineMode": engine_mode,
            "includePptxBase64": (mode == "sync") if include_pptx_base64 is None else include_pptx_base64,
        }
        if deck_title:
            payload["deckTitle"] = deck_title
        if prompt:
            payload["prompt"] = prompt
        if outline is not None:
            payload["outline"] = list(outline) if isinstance(outline, tuple) else outline
        if norm_ref is not None:
            payload["reference"] = norm_ref
        if norm_src is not None:
            payload["source"] = norm_src
        if model_id:
            payload["modelId"] = model_id
        if max_output_tokens is not None:
            payload["maxOutputTokens"] = max_output_tokens

        job = self._request_json("POST", "/v1/decks", payload)
        if mode == "async" and (wait or output_path):
            job = self.wait_for_job(job["jobId"], poll_interval=poll_interval)

        if output_path and job.get("status") == "completed":
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            pptx_bytes = (
                base64.b64decode(job["pptxBase64"])
                if job.get("pptxBase64")
                else self.download_pptx(job.get("pptxUrl") or job["jobId"])
            )
            out.write_bytes(pptx_bytes)
        return job

    def reconstruct_slide(
        self,
        *,
        image_url: Optional[str] = None,
        image_path: Optional[Union[str, Path]] = None,
        image_bytes: Optional[bytes] = None,
        image_data_url: Optional[str] = None,
        slide_id: Optional[str] = None,
        mode: str = "sync",
        engine_mode: str = "vlm",
        deck_title: Optional[str] = None,
        model_id: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        max_physical_requests: Optional[int] = None,
        include_pptx_base64: Optional[bool] = None,
        output_path: Optional[Union[str, Path]] = None,
        wait: bool = True,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        if isinstance(image_path, str) and image_path.strip().startswith("https://") and not image_url:
            image_url = image_path.strip()
            image_path = None
        if image_url and image_url.strip():
            clean_url = image_url.strip()
            if not clean_url.startswith("https://"):
                raise DeckenError("`image_url` must use HTTPS (https://...).")
            parsed_url = urllib.parse.urlparse(clean_url)
            stem = Path(parsed_url.path).stem or "slide-01"
            resolved_id = slide_id or stem
            slide_source: Dict[str, Any] = {"imageUrl": clean_url}
        else:
            data_url = normalize_image_data_url(
                image_path=image_path, image_bytes=image_bytes, image_data_url=image_data_url
            )
            resolved_id = slide_id or (Path(image_path).stem if image_path else "slide-01")
            slide_source = {"imageDataUrl": data_url}
        payload: Dict[str, Any] = {
            "mode": mode,
            "engineMode": engine_mode,
            "slideId": resolved_id,
            **slide_source,
            "includePptxBase64": (mode == "sync") if include_pptx_base64 is None else include_pptx_base64,
        }
        if deck_title:
            payload["deckTitle"] = deck_title
        if model_id:
            payload["modelId"] = model_id
        if max_output_tokens is not None:
            payload["maxOutputTokens"] = max_output_tokens
        if max_physical_requests is not None:
            payload["maxPhysicalRequests"] = max_physical_requests

        job = self._request_json("POST", "/v1/reconstruct", payload)
        if mode == "async" and (wait or output_path):
            job = self.wait_for_job(job["jobId"], poll_interval=poll_interval)

        if output_path and job.get("status") == "completed":
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            pptx_bytes = (
                base64.b64decode(job["pptxBase64"])
                if job.get("pptxBase64")
                else self.download_pptx(job.get("pptxUrl") or job["jobId"])
            )
            out.write_bytes(pptx_bytes)
        return job

    def reconstruct_deck(
        self,
        slides: Sequence[Dict[str, Any]],
        *,
        deck_title: Optional[str] = None,
        mode: Optional[str] = None,
        engine_mode: str = "vlm",
        model_id: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        output_path: Optional[Union[str, Path]] = None,
        wait: bool = True,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        if not slides:
            raise DeckenError("`reconstruct_deck` requires at least one slide.")
        normalized: List[Dict[str, str]] = []
        for idx, item in enumerate(slides):
            img_url = item.get("image_url") or item.get("imageUrl")
            img_path = item.get("image_path") or item.get("imagePath")
            if isinstance(img_path, str) and img_path.strip().startswith("https://") and not img_url:
                img_url = img_path.strip()
                img_path = None
            if img_url and str(img_url).strip():
                clean_url = str(img_url).strip()
                if not clean_url.startswith("https://"):
                    raise DeckenError("`image_url` must use HTTPS (https://...).")
                sid = (
                    item.get("slide_id")
                    or item.get("slideId")
                    or Path(urllib.parse.urlparse(clean_url).path).stem
                    or f"slide-{idx + 1:02d}"
                )
                normalized.append({"slideId": sid, "imageUrl": clean_url})
            else:
                data_url = normalize_image_data_url(
                    image_path=img_path,
                    image_bytes=item.get("image_bytes") or item.get("imageBytes"),
                    image_data_url=item.get("image_data_url") or item.get("imageDataUrl"),
                )
                sid = (
                    item.get("slide_id")
                    or item.get("slideId")
                    or (Path(img_path).stem if img_path else f"slide-{idx + 1:02d}")
                )
                normalized.append({"slideId": sid, "imageDataUrl": data_url})

        resolved_mode = mode or ("async" if len(normalized) > 1 else "sync")
        payload: Dict[str, Any] = {
            "mode": resolved_mode,
            "engineMode": engine_mode,
            "slides": normalized,
            "includePptxBase64": resolved_mode == "sync",
        }
        if deck_title:
            payload["deckTitle"] = deck_title
        if model_id:
            payload["modelId"] = model_id
        if max_output_tokens is not None:
            payload["maxOutputTokens"] = max_output_tokens

        job = self._request_json("POST", "/v1/reconstruct", payload)
        if resolved_mode == "async" and wait:
            job = self.wait_for_job(job["jobId"], poll_interval=poll_interval)

        if output_path and job.get("status") == "completed":
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            pptx_bytes = (
                base64.b64decode(job["pptxBase64"])
                if job.get("pptxBase64")
                else self.download_pptx(job.get("pptxUrl") or job["jobId"])
            )
            out.write_bytes(pptx_bytes)
        return job

    def compare_models(
        self,
        *,
        model_ids: Sequence[str],
        image_path: Optional[Union[str, Path]] = None,
        image_data_url: Optional[str] = None,
        slide_id: str = "comparison-slide",
        max_output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not model_ids:
            raise DeckenError("`compare_models` requires explicit `model_ids`.")
        data_url = normalize_image_data_url(image_path=image_path, image_data_url=image_data_url)
        runs = []
        for mid in model_ids:
            job = self.reconstruct_slide(
                image_data_url=data_url,
                slide_id=slide_id,
                mode="sync",
                engine_mode="vlm",
                model_id=mid,
                max_output_tokens=max_output_tokens,
                include_pptx_base64=False,
            )
            runs.append(
                {
                    "modelId": mid,
                    "jobId": job["jobId"],
                    "durationMs": job.get("durationMs"),
                    "wholePageMae": (job.get("metrics") or {}).get("meanWholePageMae"),
                    "totalObjectCount": (job.get("metrics") or {}).get("totalObjectCount", 0),
                    "usage": job.get("usage"),
                }
            )
        return {"slideId": slide_id, "runs": runs}
