import yfinance as yf
import pandas as pd
import numpy as np
import pandas_ta as ta
import time
import warnings
import requests
from dotenv import load_dotenv
import os
from datetime import datetime
warnings.filterwarnings('ignore')

load_dotenv()

def run_ultimate_minervini_scanner(tickers, chunk_size=100):
    all_rs_scores = []         # ตะกร้าใบที่ 1: เก็บ RS Score ของหุ้นทุกตัวในตลาด
    passed_technicals = []     # ตะกร้าใบที่ 2: เก็บเฉพาะหุ้นที่กราฟสวยผ่าน 7 ข้อ
    
    print(f"🚀 เริ่มสแกนหุ้นทั้งหมด {len(tickers)} ตัว...")
    
    for i in range(0, len(tickers), chunk_size):
        batch = tickers[i : i + chunk_size]
        print(f"📦 กำลังสแกนกลุ่มที่ {(i//chunk_size) + 1}...")
        
        try:
            # ดึงข้อมูล 2 ปีแบบเงียบๆ
            all_data = yf.download(batch, period="2y", interval="1d", progress=False)
            
            for ticker in batch:
                try:
                    if ticker not in all_data.columns.get_level_values(1): continue
                    
                    df = all_data.xs(ticker, axis=1, level=1).dropna(subset=['Close']).copy()
                    if len(df) < 252: continue # ต้องมีข้อมูลอย่างน้อย 1 ปี (252 วันทำการ)
                    
                    df['Close'] = df['Close'].ffill()

                    # --- 1. คำนวณ RS Score (เก็บของทุกคน) ---
                    close_now = float(df['Close'].iloc[-1])
                    p_start = float(df['Close'].iloc[-252])
                    p_9m = float(df['Close'].iloc[-189])
                    p_6m = float(df['Close'].iloc[-126])
                    p_3m = float(df['Close'].iloc[-63])
                    
                    perf_1y = (close_now / p_start) - 1
                    perf_9m = (close_now / p_9m) - 1
                    perf_6m = (close_now / p_6m) - 1
                    perf_3m = (close_now / p_3m) - 1
                    
                    rs_score = (perf_1y * 0.25) + (perf_9m * 0.25) + (perf_6m * 0.25) + (perf_3m * 0.25)
                    
                    if np.isnan(rs_score): continue
                    
                    # เก็บ RS Score ของ "ทุกคน" ลงตะกร้าใบแรก
                    all_rs_scores.append({'Ticker': ticker, 'RS_Score': rs_score})

                    # --- 2. คำนวณ Technical Indicators ---
                    df.ta.sma(length=50, append=True)
                    df.ta.sma(length=150, append=True)
                    df.ta.sma(length=200, append=True)
                    
                    sma50 = float(df['SMA_50'].iloc[-1])
                    sma150 = float(df['SMA_150'].iloc[-1])
                    sma200 = float(df['SMA_200'].iloc[-1])
                    
                    low_52w = float(df['Low'].tail(252).min())
                    high_52w = float(df['High'].tail(252).max())

                    # --- 3. ตรวจสอบเงื่อนไข Minervini 7 ข้อ ---
                    cond_1 = close_now > sma150 and close_now > sma200
                    cond_2 = sma150 > sma200
                    cond_3 = sma200 > float(df['SMA_200'].iloc[-22]) 
                    cond_4 = close_now > sma50
                    cond_5 = sma50 > sma150 and sma50 > sma200
                    cond_6 = close_now >= (low_52w * 1.30) 
                    cond_7 = close_now >= (high_52w * 0.75) 

                    # ถ้าผ่านกราฟ ให้เก็บข้อมูลลงตะกร้าใบที่สอง
                    if all([cond_1, cond_2, cond_3, cond_4, cond_5, cond_6, cond_7]):
                        passed_technicals.append({
                            'Ticker': ticker,
                            'Price': round(close_now, 2),
                            'SMA_50': round(sma50, 2),
                            'SMA_200': round(sma200, 2),
                            'High_52W': round(high_52w, 2)
                        })

                except Exception:
                    continue
            
            # กันโดน Yahoo แบน: พัก 2 วินาทีระหว่างกลุ่ม
            time.sleep(2) 
            
        except Exception as e:
            print(f"❌ Error กลุ่มที่ {i//chunk_size + 1}: {e}")
            time.sleep(5) # ถ้าเออเร่อ ให้พักนานหน่อย
            continue

    # --- 4. จัดอันดับ RS Rating จากคนทั้งตลาด ---
    if not all_rs_scores or not passed_technicals:
        print("❌ วันนี้ตลาดอาจจะแย่มาก ไม่มีหุ้นผ่านเกณฑ์เลย")
        return pd.DataFrame()

    # สร้าง DataFrame สำหรับคะแนน RS รวม
    rs_df = pd.DataFrame(all_rs_scores)
    rs_df['RS_Rating'] = rs_df['RS_Score'].rank(pct=True) * 100
    
    # สร้าง DataFrame สำหรับหุ้นที่ผ่านกราฟ
    tech_df = pd.DataFrame(passed_technicals)
    
    # จับคู่ (Merge) เอา RS Rating มาใส่ให้หุ้นที่ผ่านกราฟ
    final_df = pd.merge(tech_df, rs_df[['Ticker', 'RS_Rating', 'RS_Score']], on='Ticker', how='left')
    
    # --- 5. กรองข้อ 8: เอาเฉพาะตัวที่ RS Rating >= 70 ---
    final_df = final_df[final_df['RS_Rating'] >= 70].copy()
    final_df['RS_Rating'] = final_df['RS_Rating'].round(2)
    
    # เรียงลำดับความแรง
    return final_df.sort_values(by='RS_Rating', ascending=False).reset_index(drop=True)

def send_telegram(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML" # ทำให้เราทำตัวหนา <b>...</b> ได้
    }
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        print("✅ ส่งข้อความเข้า Telegram สำเร็จ!")
    else:
        print(f"❌ ส่งข้อความล้มเหลว: {response.text}")

def format_message(df):
    if df.empty:
        return "📉 <b>สรุปตลาดวันนี้:</b>\nไม่มีหุ้นตัวไหนผ่านเกณฑ์ Minervini Scanner เลยครับ"
    
    # เอาแค่ 10 อันดับแรกที่ RS Rating สูงสุด เพื่อไม่ให้ข้อความยาวเกินไป
    top_stocks = df.head(15)
    today = datetime.now().strftime('%Y-%m-%d')
    
    msg = f"🚀 <b>หุ้นเข้าเกณฑ์ Minervini วันที่ {today} ({len(df)} ตัว)</b>\n"
    msg += f"🔥 <b>Top {len(top_stocks)} RS Rating:</b>\n\n"
    
    for index, row in top_stocks.iterrows():
        msg += f"🔹 <b>{row['Ticker']}</b> | ราคา: ${row['Price']}\n"
        msg += f"   📊 RS Rating: {row['RS_Rating']} | RS Score: {row['RS_Score']}\n\n"
        
    return msg
# list of stock tickers
url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"
tickers = pd.read_csv(url, header=None)[0].tolist()

final_stocks = run_ultimate_minervini_scanner(tickers[:500])

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

message_to_send = format_message(final_stocks)
send_telegram(TELEGRAM_TOKEN, CHAT_ID, message_to_send)

print("\n🎉 สแกนเสร็จสิ้น! :")
print(final_stocks)