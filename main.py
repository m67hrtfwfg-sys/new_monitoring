import aiohttp, asyncio, os
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import SessionLocal, SiteStatus, Site, engine, Base

load_dotenv()
Base.metadata.create_all(bind=engine)
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")
connections = set()
last_status = {}

def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    user = os.getenv("DASHBOARD_USER", "admin")
    pw = os.getenv("DASHBOARD_PASS", "admin123")
    if credentials.username != user or credentials.password != pw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized",headers={"WWW-Authenticate":"Basic"},)
    return credentials.username

async def send_telegram(message):
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    if not bot_token or not chat_id: return
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, json={"chat_id": chat_id, "text": message})
        except Exception as e: print(f"Telegram Error: {e}")

async def check_and_save_site(session, s, db):
    global last_status
    max_retries = 3
    final_status = "DOWN"
    final_r_time = 0.0
    latency_threshold = 2.0 

    for attempt in range(max_retries):
        start = asyncio.get_event_loop().time()
        try:
            async with session.get(s.url, timeout=10) as r:
                r_time = round(asyncio.get_event_loop().time() - start, 3)
                if r.status == 200:
                    if r_time > latency_threshold:
                        final_status = "SLOW"
                    else:
                        final_status = "UP"
                    final_r_time = r_time
                    break 
        except Exception:
            if attempt < max_retries - 1:
                await asyncio.sleep(1) 
            continue

    
    db.add(SiteStatus(site_url=s.url, status=final_status, response_time=final_r_time))
    
    if s.url in last_status:
        old_status = last_status[s.url]
        
        if old_status != "DOWN" and final_status == "DOWN":
            await send_telegram(f"🚨 ALERT: {s.url} is DOWN after {max_retries} attempts!")
        
        elif final_status == "SLOW":
            await send_telegram(f"⚠️ WARNING: {s.url} is SLOW ({final_r_time}s)")
            
        elif (old_status == "DOWN" or old_status == "SLOW") and final_status == "UP":
            await send_telegram(f"✅ RECOVERED: {s.url} is back to normal.")
        
        elif (old_status == "UP" or old_status == "SLOW") and final_status =="DOWN" :
            await send_telegram(f"🚨 ALERT: {s.url} is DOWN")
    
    last_status[s.url] = final_status

async def monitor_loop():
    while True:
        db = SessionLocal()
        sites = db.query(Site).all()
        if not sites:
            db.close()
            await asyncio.sleep(20)
            continue
        
        async with aiohttp.ClientSession() as session:
            tasks = [check_and_save_site(session, s, db) for s in sites]
            await asyncio.gather(*tasks)
            db.commit()

        history, uptime_data = [], {}
        for s in sites:
            total = db.query(SiteStatus).filter(SiteStatus.site_url == s.url).count()
            up = db.query(SiteStatus).filter(SiteStatus.site_url == s.url, SiteStatus.status == "UP").count()
            uptime_data[s.url] = round((up/total)*100, 1) if total else 0
            
            last = db.query(SiteStatus).filter(SiteStatus.site_url == s.url).order_by(SiteStatus.id.desc()).first()
            if last:
                history.append({"site": s.url, "status": last.status, "response_time": last.response_time})
        
        db.close()

        for ws in list(connections):
            try: await ws.send_json({"history": history, "uptime": uptime_data})
            except: connections.remove(ws)
            
        await asyncio.sleep(20)

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_telegram, 'cron', hour=0, minute=0, args=["System Active ✅ - Daily Report"])
    scheduler.start()
    task = asyncio.create_task(monitor_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def get_dash(r: Request, user: str = Depends(get_current_user)):
    return templates.TemplateResponse(request=r, name="dashboard.html")

@app.get("/dashboard-data")
async def get_data(user: str = Depends(get_current_user)):
    db = SessionLocal()
    uptime, history = {}, []
    sites = db.query(Site).all()
    for s in sites:
        total = db.query(SiteStatus).filter(SiteStatus.site_url == s.url).count()
        up = db.query(SiteStatus).filter(SiteStatus.site_url == s.url, SiteStatus.status == "UP").count()
        uptime[s.url] = round((up/total)*100, 1) if total else 0
        last = db.query(SiteStatus).filter(SiteStatus.site_url == s.url).order_by(SiteStatus.id.desc()).first()
        if last: history.append({"site": s.url, "status": last.status, "response_time": last.response_time})
    db.close()
    return {"history": history, "uptime": uptime}

@app.get("/add-site")
async def add(url: str, user: str = Depends(get_current_user)):
    db = SessionLocal()
    if not db.query(Site).filter(Site.url == url).first():
        db.add(Site(url=url))
        db.commit()
    db.close()
    return {"ok": True}

@app.delete("/delete-site")
async def delete(url: str, user: str = Depends(get_current_user)):
    db = SessionLocal()
    db.query(Site).filter(Site.url == url).delete()
    db.commit()
    db.close()
    return {"ok": True}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    connections.add(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: connections.remove(ws)