import sys

try:
    from pypdf import PdfReader
except ImportError:
    print("PYPDF_MISSING")
    sys.exit(2)

for path in sys.argv[1:]:
    print("=" * 72)
    print(path)
    try:
        r = PdfReader(path)
    except Exception as e:
        print(f"  could not open: {e}")
        continue
    print(f"pages: {len(r.pages)}")
    for i, p in enumerate(r.pages):
        try:
            t = (p.extract_text() or "").strip()
        except Exception as e:
            t = f"<extract failed: {e}>"
        print(f"----- page {i + 1} -----")
        print(t if t else "<no extractable text>")
