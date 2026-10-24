"""Short-lived PDFium worker; never interprets PDF scripts or opens embedded files."""
import json
import resource
import sys
from pathlib import Path


def main():
    source, output, page_limit, pixel_limit, edge, memory_mb, cpu_seconds = sys.argv[1:]
    resource.setrlimit(resource.RLIMIT_AS, (int(memory_mb) * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_seconds), int(cpu_seconds) + 1))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    import pypdfium2 as pdfium
    try:
        document = pdfium.PdfDocument(source)
        # PDFium can silently open documents with an empty user password.
        security = pdfium.raw.FPDF_GetSecurityHandlerRevision(document)
        if security != -1:
            raise ValueError("encrypted_pdf")
        if not 1 <= len(document) <= int(page_limit):
            raise ValueError("pdf_page_limit")
        pages = []
        for index in range(len(document)):
            page = document[index]
            width, height = page.get_size()
            if width <= 0 or height <= 0 or width * height * 4 > int(pixel_limit):
                raise ValueError("pdf_pixel_limit")
            # Retain a bounded high-resolution derived page for later region reads.
            scale = min(2.0, int(edge) / max(width, height))
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            if image.width * image.height > int(pixel_limit):
                raise ValueError("pdf_pixel_limit")
            name = f"page-{index + 1}.jpg"
            image.convert("RGB").save(Path(output) / name, "JPEG", quality=92)
            pages.append({"source_page": index + 1, "width": image.width,
                          "height": image.height, "file": name})
            image.close()
            bitmap.close()
            page.close()
        document.close()
        print(json.dumps({"pages": pages}))
    except Exception as exc:
        message = str(exc)
        if "password" in message.lower() or "encrypted" in message.lower():
            code = "encrypted_pdf"
        elif "limit" in message:
            code = message
        else:
            code = "invalid_pdf"
        print(json.dumps({"error": code}))
        sys.exit(2)


if __name__ == "__main__":
    main()
