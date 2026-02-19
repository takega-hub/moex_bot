import pandas as pd
import os
from datetime import datetime

RESULTS_DIR = "research_results"
csv_path = os.path.join(RESULTS_DIR, "model_comparison.csv")

def generate_report():
    if not os.path.exists(csv_path):
        print("❌ CSV not found.")
        return

    df = pd.read_csv(csv_path)
    report_path = os.path.join(RESULTS_DIR, "comprehensive_report.md")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 📊 Comprehensive ML Model Analysis Report\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        
        f.write("## 🏆 Top Performers by ROI (Net Profit %)\n\n")
        # Ensure numeric columns
        cols = ["total_pnl_pct", "sharpe_ratio", "max_drawdown_pct", "win_rate", "profit_factor"]
        for c in cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        
        top_roi = df.sort_values("total_pnl_pct", ascending=False).head(10)
        f.write(top_roi[["ticker", "model_name", "total_pnl_pct", "sharpe_ratio", "max_drawdown_pct", "win_rate"]].to_markdown(index=False))
        f.write("\n\n")
        
        f.write("## ⚖️ Top Performers by Sharpe Ratio (Stability)\n\n")
        top_sharpe = df.sort_values("sharpe_ratio", ascending=False).head(10)
        f.write(top_sharpe[["ticker", "model_name", "sharpe_ratio", "total_pnl_pct", "profit_factor", "max_drawdown_pct"]].to_markdown(index=False))
        f.write("\n\n")
        
        f.write("## 🛡️ Safest Models (Lowest Drawdown)\n\n")
        # Only profitable ones
        profitable = df[df["total_pnl_pct"] > 0]
        if not profitable.empty:
            top_safe = profitable.sort_values("max_drawdown_pct", ascending=True).head(10)
            f.write(top_safe[["ticker", "model_name", "max_drawdown_pct", "total_pnl_pct", "profit_factor", "win_rate"]].to_markdown(index=False))
        else:
            f.write("No profitable models found to analyze drawdown safely.\n")
        f.write("\n\n")
        
        f.write("## 🤖 Model Type Analysis\n\n")
        # Extract model type (rf, xgb, ensemble, MTF)
        df["type"] = df["model_name"].apply(lambda x: "MTF" if "MTF" in x else x.split("_")[0])
        type_stats = df.groupby("type")[["total_pnl_pct", "sharpe_ratio", "win_rate"]].mean()
        f.write(type_stats.to_markdown())
        f.write("\n\n")
        
        f.write("## ⏱️ MTF Combinations Analysis\n\n")
        mtf_df = df[df["model_name"].str.contains("MTF")]
        if not mtf_df.empty:
            f.write(mtf_df.sort_values("sharpe_ratio", ascending=False).head(10)[["ticker", "model_name", "total_pnl_pct", "sharpe_ratio", "win_rate", "profit_factor"]].to_markdown(index=False))
        else:
            f.write("No MTF combinations processed yet.\n")
        f.write("\n\n")

        f.write("## 📝 Recommendations\n\n")
        best_model = top_roi.iloc[0]
        f.write(f"Based on the analysis, the best performing model is **{best_model['model_name']}** for **{best_model['ticker']}**.\n")
        f.write(f"- **ROI:** {best_model['total_pnl_pct']:.2f}%\n")
        f.write(f"- **Sharpe:** {best_model['sharpe_ratio']:.2f}\n")
        f.write(f"- **Max Drawdown:** {best_model['max_drawdown_pct']:.2f}%\n\n")
        
        f.write("### Strategy Configuration\n")
        f.write("- **Confidence Threshold:** The current backtest used default settings. Consider optimizing `confidence_threshold` for higher precision.\n")
        f.write("- **Hybrid Approach:** Combining models via voting (Hybrid Ensemble) is recommended to smooth out volatility.\n")

    print(f"📄 Report generated: {report_path}")

if __name__ == "__main__":
    generate_report()
