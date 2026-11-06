"""QR descargable para abrir el reporte del activo en el mismo sitio HTTPS."""
from io import BytesIO
from urllib.parse import urlencode
import qrcode

def report_url(origin,code):
    return origin.rstrip('/')+'/?'+urlencode(dict(reportar=code))

def image(origin,code):
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=7,border=4)
    qr.add_data(report_url(origin,code))
    qr.make(fit=True)
    out=BytesIO()
    qr.make_image(fill_color='#0f3a3f',back_color='white').save(out,format='PNG')
    return out.getvalue()
