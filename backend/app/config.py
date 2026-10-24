"""All runtime and media limits live here; no model configuration exists."""
import os
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "0.10.2"
SCOPES = ("archive.read", "media.read", "proposals.write")


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("CLMS_DATA_DIR", "./data")))
    public_origin: str = field(default_factory=lambda: os.getenv("CLMS_PUBLIC_ORIGIN", "http://127.0.0.1:18474"))
    secure_cookie: bool = field(default_factory=lambda: os.getenv("CLMS_SECURE_COOKIE", "false").lower() == "true")
    image_max_bytes: int = 25 * 1024**2
    pdf_max_bytes: int = 100 * 1024**2
    pdf_max_pages: int = 50
    version_max_pages: int = 100
    image_max_pixels: int = 40_000_000
    media_normal_edge: int = 2048
    media_high_edge: int = 4096
    media_ttl_hours: int = 72
    pdf_render_timeout: int = 20
    pdf_render_memory_mb: int = 512
    pdf_render_concurrency: int = 2
    mcp_max_pages: int = 2
    mcp_image_budget: int = 4 * 1024**2
    mcp_upload_max_bytes: int = 8 * 1024**2
    session_hours: int = 24
    max_page_size: int = 100
    frontend_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2] / "frontend" / "dist")

    def __post_init__(self):
        self.data_dir = Path(self.data_dir).absolute()
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.data_dir.is_symlink():
            raise ValueError("Data directory must not be a symlink")
        self.public_origin = self.public_origin.rstrip("/")
        for name in self.limits:
            value = os.getenv("CLMS_" + name.upper())
            if value is not None:
                parsed = int(value)
                if parsed <= 0:
                    raise ValueError(f"CLMS_{name.upper()} must be positive")
                setattr(self, name, parsed)
        if self.version_max_pages > 100 or self.max_page_size > 100 or self.mcp_max_pages > 2:
            raise ValueError("Schema limits: version/page size <=100 and MCP images <=2")

    @property
    def bootstrap_token_file(self):
        return self.data_dir / "bootstrap.token"

    @property
    def limits(self):
        names = ("image_max_bytes", "pdf_max_bytes", "pdf_max_pages", "version_max_pages",
                 "image_max_pixels", "media_normal_edge", "media_high_edge", "media_ttl_hours",
                 "pdf_render_timeout", "pdf_render_memory_mb", "pdf_render_concurrency",
                 "mcp_max_pages", "mcp_image_budget", "mcp_upload_max_bytes", "max_page_size")
        return {name: getattr(self, name) for name in names}
