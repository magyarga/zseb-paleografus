import base64
import os
from io import BytesIO, StringIO
import streamlit as st
import pandas as pd
from openai import OpenAI
from pypdf import PdfReader
from dotenv import load_dotenv
from PIL import Image
from streamlit_cropper import st_cropper

from i18n import get_text
try:
    from preprocessing import auto_preprocess_image
    PREPROCESSING_AVAILABLE = True
except ImportError:
    PREPROCESSING_AVAILABLE = False

# PDF generálás támogatása (reportlab + Unicode betűtípusok)
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    
    DEFAULT_FONT = "Helvetica"
    font_paths = [
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf"
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("CustomUnicodeFont", fp))
                DEFAULT_FONT = "CustomUnicodeFont"
                break
            except Exception:
                pass

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

load_dotenv("key.env")
if not os.getenv("OPENAI_API_KEY"):
    env_path = os.path.join(os.path.dirname(__file__), "key.env")
    load_dotenv(dotenv_path=env_path)

st.set_page_config(layout="wide", page_title="Pocket Paleographer MVP", initial_sidebar_state="collapsed")

if "app_lang" not in st.session_state:
    st.session_state["app_lang"] = "HU"

def on_lang_change():
    selected = st.session_state["lang_radio"]
    st.session_state["app_lang"] = "HU" if "Magyar" in selected else "DE"
    st.rerun()

st.sidebar.radio(
    "🌐 Nyelv / Sprache:",
    ["Magyar 🇭🇺", "Deutsch 🇩🇪"],
    index=0 if st.session_state["app_lang"] == "HU" else 1,
    key="lang_radio",
    on_change=on_lang_change
)

curr_lang = st.session_state["app_lang"]
st.title(get_text("title"))

def encode_image_bytes(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')

def pil_to_bytes(pil_image):
    buf = BytesIO()
    pil_image.save(buf, format="JPEG")
    return buf.getvalue()

def call_vision_api(client, img_bytes, sys_prompt, user_prompt):
    b64 = encode_image_bytes(img_bytes)
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": sys_prompt},
            {
                "role": "user", 
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}}
                ]
            }
        ],
        temperature=0.1
    )
    return resp.choices[0].message.content

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            if self._pageNumber > 1: # Címlapon ne legyen oldalszám
                self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.setFont(DEFAULT_FONT, 8)
        self.setFillColor(colors.HexColor("#666666"))
        self.drawRightString(612 - 54, 36, f"{self._pageNumber} / {page_count}")
        self.drawString(54, 36, "Zseb-Paleográfus MVP - Archival HTR & Regest Report")

def create_pdf_report(regeszta_text, full_text, translation_hu, translation_de, entities_df, meta):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    styles = getSampleStyleSheet()
    story = []
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName=DEFAULT_FONT, fontSize=20, leading=24, textColor=colors.HexColor("#1E3A8A"), alignment=1)
    subtitle_style = ParagraphStyle('SubTitleStyle', parent=styles['Normal'], fontName=DEFAULT_FONT, fontSize=11, leading=16, textColor=colors.HexColor("#4B5563"), alignment=1)
    h2_style = ParagraphStyle('H2Style', parent=styles['Heading2'], fontName=DEFAULT_FONT, fontSize=12, leading=16, textColor=colors.HexColor("#1E3A8A"))
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontName=DEFAULT_FONT, fontSize=9.5, leading=13.5, textColor=colors.HexColor("#1F2937"))
    meta_label_style = ParagraphStyle('MLStyle', parent=styles['Normal'], fontName=DEFAULT_FONT, fontSize=10, leading=14, textColor=colors.HexColor("#1E3A8A"))
    header_table_style = ParagraphStyle('HTStyle', parent=styles['Normal'], fontName=DEFAULT_FONT, fontSize=9, leading=11, textColor=colors.HexColor("#1E3A8A"))

    # ==================== CÍMLAP / COVER PAGE ====================
    story.append(Spacer(1, 100))
    story.append(Paragraph("📜 ZSEB-PALEOGRÁFUS", title_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Hivatalos Levéltári Oklevél Elemzési & Fordítási Riport<br/>Archival Document Analysis & Translation Report", subtitle_style))
    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="60%", thickness=1.5, color=colors.HexColor("#1E3A8A"), spaceAfter=40))
    
    # Metaadat tábla a címlapon
    meta_data = [
        [Paragraph("<b>Levéltár / Archiv:</b>", meta_label_style), Paragraph(meta.get('archive', 'N/A'), body_style)],
        [Paragraph("<b>Jelzet / Signatur:</b>", meta_label_style), Paragraph(meta.get('shelfmark', 'N/A'), body_style)],
        [Paragraph("<b>Dokumentum címe / Titel:</b>", meta_label_style), Paragraph(meta.get('title', 'N/A'), body_style)],
        [Paragraph("<b>Kutató / Bearbeiter:</b>", meta_label_style), Paragraph(meta.get('researcher', 'N/A'), body_style)],
        [Paragraph("<b>Dátum / Datum:</b>", meta_label_style), Paragraph(meta.get('date', 'N/A'), body_style)],
    ]
    meta_table = Table(meta_data, colWidths=[150, 354])
    meta_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
    ]))
    story.append(meta_table)
    
    story.append(PageBreak()) # Ugrás a tartalomra

    # ==================== 1. REGESZTA ====================
    if regeszta_text:
        story.append(Paragraph("1. Regest / Regeszta", h2_style))
        story.append(Spacer(1, 4))
        for para in regeszta_text.split('\n\n'):
            clean_p = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(clean_p, body_style))
            story.append(Spacer(1, 4))
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E1"), spaceAfter=10))
        
    # ==================== 2. TEXTUS ====================
    story.append(Paragraph("2. Textus (Original)", h2_style))
    story.append(Spacer(1, 4))
    for line in full_text.split('\n'):
        clean_line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        if clean_line.strip():
            story.append(Paragraph(clean_line, body_style))
        else:
            story.append(Spacer(1, 3))
    story.append(Spacer(1, 8))

    # ==================== 3. FORDÍTÁSOK ====================
    if translation_hu or translation_de:
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E1"), spaceAfter=10))
        story.append(Paragraph("3. Übersetzungen / Fordítások", h2_style))
        story.append(Spacer(1, 4))
        
        if translation_de:
            story.append(Paragraph("<b>Deutsche Übersetzung:</b>", body_style))
            story.append(Spacer(1, 2))
            for para in translation_de.split('\n\n'):
                story.append(Paragraph(para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'), body_style))
                story.append(Spacer(1, 3))
            story.append(Spacer(1, 6))

        if translation_hu:
            story.append(Paragraph("<b>Magyar fordítás:</b>", body_style))
            story.append(Spacer(1, 2))
            for para in translation_hu.split('\n\n'):
                story.append(Paragraph(para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'), body_style))
                story.append(Spacer(1, 3))
            story.append(Spacer(1, 6))

    # ==================== 4. ENTITÁSOK ====================
    if entities_df is not None and not entities_df.empty:
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E1"), spaceAfter=10))
        story.append(Paragraph("4. Register & Entitäten", h2_style))
        story.append(Spacer(1, 6))
        
        table_data = [[Paragraph(f"<b>{col}</b>", header_table_style) for col in entities_df.columns]]
        for _, row in entities_df.iterrows():
            row_cells = []
            for val in row.values:
                clean_val = str(val).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                row_cells.append(Paragraph(clean_val, body_style))
            table_data.append(row_cells)
        
        t = Table(table_data, colWidths=[100, 150, 254])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F1F5F9")),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#94A3B8")),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(t)
            
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()

if "editor_area" not in st.session_state:
    st.session_state["editor_area"] = ""
if "cached_images" not in st.session_state:
    st.session_state.cached_images = []
if "last_file_name" not in st.session_state:
    st.session_state.last_file_name = ""
if "summary_regeszta" not in st.session_state:
    st.session_state.summary_regeszta = ""
if "full_combined_text" not in st.session_state:
    st.session_state.full_combined_text = ""
if "translation_hu" not in st.session_state:
    st.session_state.translation_hu = ""
if "translation_de" not in st.session_state:
    st.session_state.translation_de = ""
if "entities_df" not in st.session_state:
    st.session_state.entities_df = None

env_api_key = os.getenv("OPENAI_API_KEY")
if not env_api_key:
    try:
        env_api_key = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        env_api_key = ""

col1, col2 = st.columns(2)

with col1:
    st.header(get_text("doc_upload"))
    uploaded_file = st.file_uploader(get_text("choose_file"), type=["pdf", "jpg", "jpeg"], key=f"uploader_{curr_lang}")
    
    if uploaded_file is not None:
        if st.session_state.last_file_name != uploaded_file.name:
            st.session_state.cached_images = []
            st.session_state.last_file_name = uploaded_file.name
            
            uploaded_file.seek(0)
            if uploaded_file.name.lower().endswith('.pdf'):
                try:
                    reader = PdfReader(uploaded_file)
                    extracted = []
                    for page in reader.pages:
                        for img_obj in page.images:
                            extracted.append(img_obj.data)
                    st.session_state.cached_images = extracted
                except Exception as e:
                    st.error(f"Error reading PDF: {e}")
            else:
                st.session_state.cached_images = [uploaded_file.read()]

    selected_crop_img_bytes = None

    if st.session_state.cached_images:
        total_pages = len(st.session_state.cached_images)
        st.subheader(get_text("select_page"))
        
        if total_pages > 1:
            selected_page_num = st.slider(
                get_text("which_page"), 
                min_value=1, 
                max_value=total_pages, 
                value=1,
                key=f"slider_{curr_lang}"
            )
        else:
            selected_page_num = 1
            st.info(get_text("single_page_info"))
        
        raw_img_bytes = st.session_state.cached_images[selected_page_num - 1]
        pil_img = Image.open(BytesIO(raw_img_bytes))

        process_mode = st.radio(
            get_text("mode_label"),
            [get_text("mode_orig"), get_text("mode_auto"), get_text("mode_crop")],
            key=f"proc_mode_{curr_lang}"
        )

        if process_mode == get_text("mode_crop"):
            st.caption(get_text("crop_caption"))
            cropped_pil = st_cropper(
                pil_img, 
                realtime_update=True, 
                box_color='#FF4B4B', 
                aspect_ratio=None,
                key=f"cropper_{curr_lang}"
            )
            selected_crop_img_bytes = pil_to_bytes(cropped_pil)
            st.image(cropped_pil, caption=f"Vágott {selected_page_num}. oldal", use_container_width=True)

        elif process_mode == get_text("mode_auto"):
            if PREPROCESSING_AVAILABLE:
                with st.spinner("OpenCV előfeldolgozás folyamatban..."):
                    auto_bytes = auto_preprocess_image(raw_img_bytes)
                    selected_crop_img_bytes = auto_bytes
                    auto_pil = Image.open(BytesIO(auto_bytes))
                    st.caption(get_text("auto_caption"))
                    st.image(auto_pil, caption=f"Előfeldolgozott {selected_page_num}. oldal", use_container_width=True)
            else:
                st.warning("⚠️ Az előfeldolgozó modul nem található. Az eredeti képet használjuk.")
                selected_crop_img_bytes = raw_img_bytes
                st.image(pil_img, caption=f"Eredeti {selected_page_num}. oldal", use_container_width=True)

        else:
            selected_crop_img_bytes = raw_img_bytes
            st.image(pil_img, caption=f"Eredeti {selected_page_num}. oldal", use_container_width=True)

with col2:
    st.header(get_text("htr_header"))
    
    if env_api_key:
        st.success(get_text("api_key_loaded"))
        api_key = env_api_key
    else:
        api_key = st.text_input(get_text("api_key_prompt"), type="password", key=f"api_in_{curr_lang}")
    
    if st.session_state.cached_images and selected_crop_img_bytes:
        btn_col1, btn_col2 = st.columns([2, 1])
        
        with btn_col1:
            start_analysis = st.button(get_text("btn_analyze"), key=f"btn_an_{curr_lang}")
        with btn_col2:
            clear_all = st.button(get_text("btn_clear"), key=f"btn_clr_{curr_lang}")
            
        if clear_all:
            st.session_state["editor_area"] = ""
            st.session_state.summary_regeszta = ""
            st.session_state.full_combined_text = ""
            st.session_state.translation_hu = ""
            st.session_state.translation_de = ""
            st.session_state.entities_df = None
            st.rerun()

        if start_analysis:
            if not api_key:
                st.error("Missing OpenAI API Key!")
            else:
                with st.spinner("Analyzing page (HTR processing)..."):
                    try:
                        client = OpenAI(api_key=api_key)
                        
                        sys_prompt = (
                            "You are an expert academic paleographer and archivist specializing in early modern European manuscripts. "
                            "Your task is to analyze the provided historical document image and strictly follow the structural formatting guidelines. "
                            "You must maintain extreme accuracy, preserve original spelling, and expand abbreviations using square brackets []. "
                            "Do not include any conversational filler, meta-commentary, or introductory phrases. Output only the requested structured content."
                        )
                        
                        user_prompt = (
                            f"Analyze the historical document page {selected_page_num}. You must output your response strictly inside the specified Markdown sections below. Do not deviate from this format.\n\n"
                            f"--- PAGE {selected_page_num} ANALYSIS ---\n\n"
                            "### 1. DOCUMENT TYPOLOGY AND LANGUAGE\n"
                            "- **Language(s):** [Identify primary and secondary languages, e.g., Latin, German, Hungarian]\n"
                            "- **Script Type:** [Identify the script, e.g., Neo-Gothic cursive, Humanist minuscule]\n\n"
                            "### 2. VERBATIM TRANSCRIPTION (LINE-BY-LINE)\n"
                            "Provide a strict line-by-line transcription. Do not skip lines. Use square brackets for expansions.\n"
                            "```text\n"
                            "[Insert Line 1 here]\n"
                            "[Insert Line 2 here]\n"
                            "...\n"
                            "```\n\n"
                            "### 3. PALEOGRAPHICAL NOTES\n"
                            "- **Marginalia:** [Notes on margins, or \"None\"]\n"
                            "- **Seals/Stamps:** [Description of seals, or \"None\"]\n"
                            "- **Condition/Ink:** [Brief notes on legibility, ink, or damage]\n\n"
                            "### 4. SUMMARY (REGESZTA)\n"
                            "[Provide a concise 2-3 sentence summary of this specific page in Hungarian or German, depending on the document's primary context.]\n\n"
                            "### 5. EXTRACTED ENTITIES\n"
                            "- **Names:** [Comma-separated list of historical persons]\n"
                            "- **Locations:** [Comma-separated list of places]\n"
                            "- **Dates:** [Comma-separated list of dates mentioned]\n"
                        )
                        
                        output = call_vision_api(client, selected_crop_img_bytes, sys_prompt, user_prompt)
                        
                        refusal_keywords = ["unable to transcribe", "sorry, i can't assist", "cannot assist with identifying", "unable to read"]
                        if any(refusal in output.lower() for refusal in refusal_keywords):
                            st.warning("⚠️ API biztonsági gyorsítótár észlelve. Automatikus 2. körös áttörés...")
                            
                            pil_retry = Image.open(BytesIO(selected_crop_img_bytes))
                            w, h = pil_retry.size
                            pil_retry = pil_retry.resize((w - 1, h - 1))
                            retry_bytes = pil_to_bytes(pil_retry)
                            
                            output = call_vision_api(client, retry_bytes, sys_prompt, user_prompt)

                        current_val = st.session_state.get("editor_area", "")
                        if current_val.strip():
                            st.session_state["editor_area"] = f"{current_val}\n\n=========================================\n\n{output}"
                        else:
                            st.session_state["editor_area"] = output
                            
                        st.success(f"✅ Page {selected_page_num} successfully transcribed!")
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"API Error: {e}")

    st.subheader(get_text("workspace_header"))
    
    edited_text = st.text_area(
        label=get_text("workspace_label"),
        height=300,
        key=f"editor_area_{curr_lang}" if "editor_area" not in st.session_state else "editor_area"
    )

    if st.session_state.get("editor_area", "").strip():
        st.markdown("---")
        st.subheader(get_text("synth_header"))
        
        synth_col1, synth_col2 = st.columns(2)
        
        with synth_col1:
            if st.button(get_text("btn_synth"), use_container_width=True, key=f"btn_syn_{curr_lang}"):
                if not api_key:
                    st.error("Missing OpenAI API Key!")
                else:
                    with st.spinner("Synthesizing full document..."):
                        try:
                            client = OpenAI(api_key=api_key)
                            
                            synth_prompt = (
                                "Perform 3 tasks based on the provided archival transcription:\n\n"
                                "1. **REGESZTA / REGEST:** A 2-3 paragraph professional historical summary written strictly in Hungarian (Magyar nyelven).\n\n"
                                "2. **FULL COMBINED TEXTUS:** Combine all HTR transcriptions into a continuous, line-by-line textus.\n\n"
                                "3. **STRUCTURED ENTITIES (JSON):** Extract entities in JSON format:\n"
                                "```json\n"
                                "[\n"
                                '  {"Típus / Typ": "Személynév / Person", "Megnevezés / Name": "Ferdinandus I", "Kontextus / Rolle": "Magyar király / König"},\n'
                                '  {"Típus / Typ": "Helynév / Ort", "Megnevezés / Name": "Posonium", "Kontextus / Rolle": "Kiadás helye"},\n'
                                '  {"Típus / Typ": "Dátum / Datum", "Megnevezés / Name": "1552. junii 12.", "Kontextus / Rolle": "Ausstellungsdatum"}\n'
                                "]\n"
                                "```\n\n"
                                "Format strictly as:\n"
                                "--- REGESZTA ---\n"
                                "[Regest text in Hungarian]\n\n"
                                "--- TELJES TEXTUS ---\n"
                                "[Combined textus]\n\n"
                                "```json\n"
                                "[JSON array]\n"
                                "```"
                            )
                            
                            active_text = st.session_state.get("editor_area", "")
                            synth_response = client.chat.completions.create(
                                model="gpt-4o",
                                messages=[
                                    {"role": "system", "content": "You are a professional historical archivist and expert paleographer."},
                                    {"role": "user", "content": f"{synth_prompt}\n\nTARTALOM:\n{active_text}"}
                                ],
                                temperature=0.1
                            )
                            
                            full_synth_output = synth_response.choices[0].message.content
                            
                            regeszta_part = ""
                            textus_part = ""
                            json_str = ""
                            
                            if "--- REGESZTA ---" in full_synth_output and "--- TELJES TEXTUS ---" in full_synth_output:
                                p1 = full_synth_output.split("--- TELJES TEXTUS ---")
                                regeszta_part = p1[0].replace("--- REGESZTA ---", "").strip()
                                
                                if "```json" in p1[1]:
                                    p2 = p1[1].split("```json")
                                    textus_part = p2[0].strip()
                                    json_str = p2[1].split("```")[0].strip()
                                else:
                                    textus_part = p1[1].strip()
                            else:
                                regeszta_part = full_synth_output
                                
                            st.session_state.summary_regeszta = regeszta_part
                            st.session_state.full_combined_text = textus_part
                            
                            if json_str:
                                try:
                                    json_data = pd.read_json(StringIO(json_str))
                                    st.session_state.entities_df = json_data
                                except Exception:
                                    pass
                                    
                            st.success("✅ Synthesis complete!")
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"Synthesis error: {e}")

        with synth_col2:
            if st.session_state.full_combined_text:
                if st.button(get_text("btn_trans"), use_container_width=True, key=f"btn_tr_{curr_lang}"):
                    if not api_key:
                        st.error("Missing OpenAI API Key!")
                    else:
                        with st.spinner("Translating document..."):
                            try:
                                client = OpenAI(api_key=api_key)
                                
                                trans_prompt = (
                                    "Provide two translations for this Latin text:\n\n"
                                    "1. **MAGYAR FORDÍTÁS:** Accurate Hungarian historical translation.\n\n"
                                    "2. **DEUTSCHE ÜBERSETZUNG:** Accurate German historical translation.\n\n"
                                    "Format:\n"
                                    "--- MAGYAR FORDÍTÁS ---\n"
                                    "[Hungarian text]\n\n"
                                    "--- DEUTSCHE ÜBERSETZUNG ---\n"
                                    "[German text]"
                                )
                                
                                trans_response = client.chat.completions.create(
                                    model="gpt-4o",
                                    messages=[
                                        {"role": "system", "content": "You are an expert historical translator."},
                                        {"role": "user", "content": f"{trans_prompt}\n\nTEXTUS:\n{st.session_state.full_combined_text}"}
                                    ],
                                    temperature=0.2
                                )
                                
                                trans_output = trans_response.choices[0].message.content
                                
                                if "--- MAGYAR FORDÍTÁS ---" in trans_output and "--- DEUTSCHE ÜBERSETZUNG ---" in trans_output:
                                    t_parts = trans_output.split("--- DEUTSCHE ÜBERSETZUNG ---")
                                    st.session_state.translation_hu = t_parts[0].replace("--- MAGYAR FORDÍTÁS ---", "").strip()
                                    st.session_state.translation_de = t_parts[1].strip()
                                else:
                                    st.session_state.translation_hu = trans_output
                                    
                                st.success("✅ Translations generated!")
                                st.rerun()
                                
                            except Exception as e:
                                st.error(f"Translation error: {e}")

        if st.session_state.summary_regeszta:
            st.markdown(f"### {get_text('regeszta_title')}")
            st.info(st.session_state.summary_regeszta)
            
        if st.session_state.full_combined_text:
            st.markdown(f"### {get_text('textus_title')}")
            
            tab1, tab2, tab3 = st.tabs([get_text("tab_latin"), get_text("tab_hu"), get_text("tab_de")])
            
            with tab1:
                st.text_area(
                    label=get_text("latin_label"),
                    value=st.session_state.full_combined_text,
                    height=300,
                    key=f"textus_area_{curr_lang}"
                )
            with tab2:
                if st.session_state.translation_hu:
                    st.text_area(
                        label=get_text("trans_hu_label"),
                        value=st.session_state.translation_hu,
                        height=300,
                        key=f"trans_hu_area_{curr_lang}"
                    )
                else:
                    st.caption(get_text("trans_caption"))
            with tab3:
                if st.session_state.translation_de:
                    st.text_area(
                        label=get_text("trans_de_label"),
                        value=st.session_state.translation_de,
                        height=300,
                        key=f"trans_de_area_{curr_lang}"
                    )
                else:
                    st.caption(get_text("trans_caption"))
            
        if st.session_state.entities_df is not None:
            st.markdown(f"### {get_text('entities_title')}")
            st.dataframe(st.session_state.entities_df, use_container_width=True)
            
            csv_data = st.session_state.entities_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label=get_text("btn_download_csv"),
                data=csv_data,
                file_name="register_entitaeten.csv",
                mime="text/csv",
                key=f"dl_csv_{curr_lang}"
            )

    st.markdown("---")
    st.subheader(get_text("export_header"))
    
    # Új: Levéltári metaadatok beviteli mezői az export előtt
    with st.expander("🏛️ Levéltári Metaadatok & Címlap Testreszabása", expanded=True):
        meta_col1, meta_col2 = st.columns(2)
        with meta_col1:
            meta_archive = st.text_input("Levéltár / Archiv:", value="Magyar Nemzeti Levéltár Országos Levéltára (MNL OL)")
            meta_shelfmark = st.text_input("Levéltári Jelzet / Signatur:", value="DF 203.412")
            meta_title = st.text_input("Oklevél tárgya / Titel:", value="I. Ferdinánd király parancsa Castaldónak és Nádasdy Tamásnak")
        with meta_col2:
            meta_researcher = st.text_input("Kutató / Bearbeiter:", value="Dr. Zseb-Paleográfus")
            meta_date = st.text_input("Kutatás dátuma / Datum:", value="2026. november")

    meta_dict = {
        "archive": meta_archive,
        "shelfmark": meta_shelfmark,
        "title": meta_title,
        "researcher": meta_researcher,
        "date": meta_date
    }

    exp_col1, exp_col2 = st.columns(2)
    
    final_text_to_download = st.session_state.full_combined_text if st.session_state.full_combined_text else st.session_state.get("editor_area", "")
    
    with exp_col1:
        st.download_button(
            label=get_text("btn_download_txt"),
            data=final_text_to_download,
            file_name="urkunde_textus.txt",
            mime="text/plain",
            use_container_width=True,
            key=f"dl_txt_{curr_lang}"
        )
        
    with exp_col2:
        if REPORTLAB_AVAILABLE:
            if final_text_to_download.strip():
                pdf_data = create_pdf_report(
                    st.session_state.summary_regeszta, 
                    final_text_to_download,
                    st.session_state.translation_hu,
                    st.session_state.translation_de,
                    st.session_state.entities_df,
                    meta_dict
                )
                st.download_button(
                    label=get_text("btn_download_pdf"),
                    data=pdf_data,
                    file_name="taschen_palaeograph_jelentes.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"dl_pdf_{curr_lang}"
                )
            else:
                st.info(get_text("pdf_info"))
        else:
            st.warning(get_text("pdf_warn"))