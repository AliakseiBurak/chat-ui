from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
import requests
import os
import io
import json
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

pdfmetrics.registerFont(TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))

LOG_DIR = "log"
SESSION_DIR = os.path.join(LOG_DIR, "sessions")
ERROR_DIR = os.path.join(LOG_DIR, "errors")

app = FastAPI()

def _log_session(user_msg: str, model: str, reply: str, elapsed_secs: float = 0):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(SESSION_DIR, f"{ts}.log")
        with open(path, "w") as f:
            f.write(f"timestamp: {datetime.now().isoformat()}\n")
            f.write(f"model: {model}\n")
            f.write(f"elapsed_secs: {elapsed_secs:.2f}\n")
            f.write(f"user: {user_msg}\n")
            f.write(f"bot: {reply}\n")
    except Exception:
        pass

def _log_error(kind: str, detail: str):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(ERROR_DIR, f"{ts}.log")
        with open(path, "w") as f:
            f.write(f"timestamp: {datetime.now().isoformat()}\n")
            f.write(f"kind: {kind}\n")
            f.write(f"detail: {detail}\n")
    except Exception:
        pass

app.mount("/static", StaticFiles(directory="."), name="static")

@app.middleware("http")
async def block_dotfiles(request: Request, call_next):
    if "/static/." in request.url.path:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await call_next(request)

@app.get("/.well-known/{path:path}")
async def well_known():
    return JSONResponse({})

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return HTMLResponse(open("index.html").read())

# New endpoint to fetch available models from Ollama
@app.get("/models")
async def list_models():
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return JSONResponse({"models": models})
    except Exception as e:
        return JSONResponse({"models": []}, status_code=500)

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    user_msg = data.get("message", "").strip()
    model = data.get("model", "llama3.2:1b")

    if not user_msg:
        return JSONResponse({"reply": "Please type a message.", "model": model}, status_code=400)

    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    start_time = time.time()

    async def generate():
        try:
            payload = {"model": model, "prompt": user_msg, "stream": True}
            with requests.post(f"{ollama_url}/api/generate", json=payload, stream=True, timeout=600) as resp:
                if resp.status_code == 404:
                    err_msg = f"Model '{model}' not found. Pull it with `ollama pull {model}`"
                    yield f"data: {json.dumps({'error': err_msg})}\n\n"
                    return
                resp.raise_for_status()
                full_reply = []
                for line in resp.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        full_reply.append(token)
                        yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"
                        if chunk.get("done"):
                            elapsed = time.time() - start_time
                            reply = "".join(full_reply)
                            _log_session(user_msg, model, reply, elapsed)
                            yield f"data: {json.dumps({'done': True, 'model': model, 'elapsed_secs': round(elapsed, 2)})}\n\n"
        except requests.exceptions.ConnectionError:
            _log_error("ConnectionError", f"Failed to connect to Ollama at {ollama_url}")
            yield f"data: {json.dumps({'error': 'Ollama not running. Start it with `ollama serve`'})}\n\n"
        except Exception as e:
            _log_error("ChatError", str(e))
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

@app.post("/export")
async def export_chat(request: Request):
    data = await request.json()
    chat_history = data.get("history", [])

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 50
    y = height - margin
    line_height = 18

    c.setFont("DejaVu-Bold", 16)
    c.setFillColor(HexColor("#2563eb"))
    c.drawString(margin, y, "Chat History")
    y -= 8
    c.setStrokeColor(HexColor("#e5e7eb"))
    c.line(margin, y, width - margin, y)
    y -= 20

    user_color = HexColor("#1e3a8a")
    bot_color = HexColor("#111827")
    user_bg = HexColor("#dbeafe")
    bot_bg = HexColor("#f3f4f6")
    label_color = HexColor("#6b7280")

    for entry in chat_history:
        if y < 60:
            c.showPage()
            y = height - margin

        text = entry.get("text", "")
        role = entry.get("role", "user")
        model = entry.get("model")
        elapsed = entry.get("elapsed_secs")

        bg = user_bg if role == "user" else bot_bg
        fg = user_color if role == "user" else bot_color

        # Draw role label
        c.setFont("DejaVu-Bold", 9)
        c.setFillColor(label_color)
        label = role.capitalize()
        if model:
            label += f"  |  {model}"
            if elapsed:
                label += f"  |  {elapsed}s"
        c.drawString(margin + 4, y + 2, label)
        y -= 14

        # Draw message text with word wrap
        c.setFont("DejaVu", 10)
        c.setFillColor(fg)
        words = text.split()
        line = ""
        for word in words:
            test = line + (" " if line else "") + word
            if c.stringWidth(test, "DejaVu", 10) < width - 2 * margin - 16:
                line = test
            else:
                c.drawString(margin + 8, y, line)
                y -= line_height
                line = word
                if y < 50:
                    c.showPage()
                    y = height - margin
                    c.setFont("DejaVu", 10)
                    c.setFillColor(fg)
        if line:
            c.drawString(margin + 8, y, line)
            y -= line_height + 4

    c.save()
    buffer.seek(0)

    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=chat.pdf"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=int(os.getenv("PORT", "8888")))
