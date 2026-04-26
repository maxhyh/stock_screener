
import akshare as ak
import pandas as pd
import datetime
import os
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import warnings

warnings.filterwarnings('ignore')

# ================= 配置区域 =================
# 脚本现在在 data/ 目录中，直接使用当前目录
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")
META_FILE = os.path.join(DATA_DIR, "stock_info.csv")

# 5 Year Window
START_DATE = (datetime.date.today() - datetime.timedelta(days=365*5)).strftime("%Y%m%d")
END_DATE = datetime.date.today().strftime("%Y%m%d")

# Optimization Parameters
MAX_WORKERS = 6       # Conservative concurrency to avoid bans
RETRY_COUNT = 3       # Robustness
BATCH_SIZE = 500      # Memory hygiene (though standard desktops handle 5000 stocks fine)
# ===========================================

def get_stock_list():
    """Fetch all A-share codes"""
    print("Fetching stock list...")
    try:
        df = ak.stock_zh_a_spot_em()
        return df['代码'].tolist()
    except Exception as e:
        print(f"Failed to get stock list: {e}")
        return []

def safe_rename(df, rename_map):
    """Safely rename columns, verifying handling changes in AKShare API."""
    cols_to_rename = {k: v for k, v in rename_map.items() if k in df.columns}
    if len(cols_to_rename) < len(rename_map):
        # Optional: Log missing columns if critical
        pass
    return df.rename(columns=cols_to_rename)

def safe_download_history(code):
    """Download with retry and random sleep"""
    for i in range(RETRY_COUNT):
        try:
            # Random sleep to be nice to the server
            time.sleep(random.uniform(0.05, 0.2))
            
            # Fetch Data
            df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=START_DATE, end_date=END_DATE, adjust="qfq")
            
            if df is None or df.empty:
                return None
            
            # Standardize Columns
            rename_map = {
                '日期': 'trade_date', '开盘': 'open', '收盘': 'close', 
                '最高': 'high', '最低': 'low', '成交量': 'vol', 
                '成交额': 'amount', '换手率': 'turnover_rate', 
                '涨跌幅': 'pct_chg', '振幅': 'amplitude', '涨跌额': 'change'
            }
            # Use safe rename
            df = safe_rename(df, rename_map)
            
            # Add Code column
            df['ts_code'] = code
            
            # Ensure Date format YYYYMMDD
            if 'trade_date' in df.columns:
                 # Convert to string format YYYYMMDD for consistency
                 df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')

            # Select relevant columns only
            target_cols = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg', 'turnover_rate']
            final_cols = [c for c in target_cols if c in df.columns]
            
            return df[final_cols]
            
        except Exception as e:
            if i == RETRY_COUNT - 1:
                return None
            time.sleep(1 * (i + 1)) # Backoff strategy
    return None

def fetch_metadata_map():
    """
    Fetch Name and Industry.
    This logic comes from the 'Feature-Rich' version. 
    The 'User Script' skipped this implementation.
    """
    print("\nFetching Stock Metadata (Name, Industry)...")
    
    # 1. Names (Spot Data)
    try:
        df_spot = ak.stock_zh_a_spot_em()
        # [Optimized] Vectorized Metadata Creation
        # Avoid iterrows for Dictionary creation
        print(f"Fetch metadata for {len(df_spot)} stocks...")
        records = df_spot[['代码', '名称']].to_dict('records')
        meta_dict = {r['代码']: {'name': r['名称'], 'industry': ''} for r in records}
    except Exception as e:
        print(f"Failed to fetch spot data: {e}")
        return {}
        
    # 2. Industry Mapping
    try:
        df_ind = ak.stock_board_industry_name_em()
        ind_list = df_ind['板块名称'].tolist()
        print(f"Scanning {len(ind_list)} Industries for mapping...")
        
        def fetch_ind_cons(ind_name):
            try:
                df = ak.stock_board_industry_cons_em(symbol=ind_name)
                return ind_name, df['代码'].tolist()
            except Exception:
                return ind_name, []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_ind_cons, name): name for name in ind_list}
            for future in tqdm(as_completed(futures), total=len(ind_list), desc="Mapping Industries"):
                ind_name, codes = future.result()
                for c in codes:
                    if c in meta_dict:
                        meta_dict[c]['industry'] = ind_name
    except Exception as e:
        print(f"Industry fetch failed: {e}")
        
    return meta_dict

def main():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    codes = get_stock_list()
    if not codes:
        print("No codes found.")
        return

    print(f"Tasks: Download {len(codes)} stocks ({START_DATE}-{END_DATE})")
    print(f"Config: Workers={MAX_WORKERS}")

    all_data = []
    
    # 1. Price History
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_code = {executor.submit(safe_download_history, code): code for code in codes}
        
        for future in tqdm(as_completed(future_to_code), total=len(codes), desc="Price History"):
            res = future.result()
            if res is not None:
                all_data.append(res)
    
    if all_data:
        print("Merging and optimizing data...")
        full_df = pd.concat(all_data, ignore_index=True)
        
        # Numeric Conversion
        numeric_cols = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg', 'turnover_rate']
        for col in numeric_cols:
            if col in full_df.columns:
                full_df[col] = pd.to_numeric(full_df[col], errors='coerce')
        
        # Optimization: Use Category for ts_code
        full_df['ts_code'] = full_df['ts_code'].astype('category')
        
        print(f"Saving {len(full_df)} rows to {OUTPUT_FILE}...")
        full_df.to_parquet(OUTPUT_FILE, index=False, compression='snappy')
        print("Price data saved.")
    else:
        print("No price data downloaded.")
    
    # 2. Metadata (Industry/Name)
    try:
        meta_dict = fetch_metadata_map()
        if meta_dict:
            meta_df = pd.DataFrame.from_dict(meta_dict, orient='index').reset_index().rename(columns={'index':'ts_code'})
            print(f"Saving metadata to {META_FILE}...")
            meta_df.to_csv(META_FILE, index=False)
    except Exception as e:
        print(f"Metadata error: {e}")

    print("All tasks completed.")

if __name__ == "__main__":
    main()
