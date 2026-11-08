import cv2
import numpy as np

def auto_preprocess_image(image_bytes: bytes) -> bytes:
    """
    Automatikus előfeldolgozás levéltári képekhez:
    Dőléskorrekció (Deskew) és CLAHE adaptív kontrasztkiemelés.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        return image_bytes

    # 1. Grayscale & Zajcsökkentés
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    # 2. Dőléskorrekció (Deskew)
    thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) > 0:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        
        if abs(angle) > 0.5:
            (h, w) = img.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. Adaptív Kontrasztkiemelés (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced_gray = clahe.apply(gray)
    
    final_img = cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2BGR)

    is_success, buffer = cv2.imencode(".jpg", final_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if is_success:
        return buffer.tobytes()
    return image_bytes