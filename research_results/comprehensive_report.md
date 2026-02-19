# 📊 Comprehensive ML Model Analysis Report

**Date:** 2026-02-18 19:27

## 🏆 Top Performers by ROI (Net Profit %)

| ticker   | model_name                   |   total_pnl_pct |   sharpe_ratio |   max_drawdown_pct |   win_rate |
|:---------|:-----------------------------|----------------:|---------------:|-------------------:|-----------:|
| GAZPF    | ensemble_GAZPF_15_mtf_15min  |        1.45112  |       4.25517  |           0.188593 |    55.3571 |
| GAZPF    | quad_ensemble_GAZPF_15_15min |        1.14292  |       3.28538  |           0.266868 |    50.8772 |
| GAZPF    | ensemble_GAZPF_15_15min      |        1.09969  |       3.18427  |           0.266895 |    50.8772 |
| GAZPF    | ensemble_GAZPF_15_15min      |        1.09969  |       3.18427  |           0.266895 |    50.8772 |
| GAZPF    | ensemble_GAZPF_15_15min      |        0.194181 |       0.117789 |           1.92536  |    36.5672 |

## ⚖️ Top Performers by Sharpe Ratio (Stability)

| ticker   | model_name                   |   sharpe_ratio |   total_pnl_pct |   profit_factor |   max_drawdown_pct |
|:---------|:-----------------------------|---------------:|----------------:|----------------:|-------------------:|
| GAZPF    | ensemble_GAZPF_15_mtf_15min  |       4.25517  |        1.45112  |         1.79223 |           0.188593 |
| GAZPF    | quad_ensemble_GAZPF_15_15min |       3.28538  |        1.14292  |         1.57141 |           0.266868 |
| GAZPF    | ensemble_GAZPF_15_15min      |       3.18427  |        1.09969  |         1.54876 |           0.266895 |
| GAZPF    | ensemble_GAZPF_15_15min      |       3.18427  |        1.09969  |         1.54876 |           0.266895 |
| GAZPF    | ensemble_GAZPF_15_15min      |       0.117789 |        0.194181 |         1.01667 |           1.92536  |

## 🛡️ Safest Models (Lowest Drawdown)

| ticker   | model_name                   |   max_drawdown_pct |   total_pnl_pct |   profit_factor |   win_rate |
|:---------|:-----------------------------|-------------------:|----------------:|----------------:|-----------:|
| GAZPF    | ensemble_GAZPF_15_mtf_15min  |           0.188593 |        1.45112  |         1.79223 |    55.3571 |
| GAZPF    | quad_ensemble_GAZPF_15_15min |           0.266868 |        1.14292  |         1.57141 |    50.8772 |
| GAZPF    | ensemble_GAZPF_15_15min      |           0.266895 |        1.09969  |         1.54876 |    50.8772 |
| GAZPF    | ensemble_GAZPF_15_15min      |           0.266895 |        1.09969  |         1.54876 |    50.8772 |
| GAZPF    | ensemble_GAZPF_15_15min      |           1.92536  |        0.194181 |         1.01667 |    36.5672 |

## 🤖 Model Type Analysis

| type     |   total_pnl_pct |   sharpe_ratio |   win_rate |
|:---------|----------------:|---------------:|-----------:|
| ensemble |         0.96117 |        2.68538 |    48.4197 |
| quad     |         1.14292 |        3.28538 |    50.8772 |

## ⏱️ MTF Combinations Analysis

No MTF combinations processed yet.


## 📝 Recommendations

Based on the analysis, the best performing model is **ensemble_GAZPF_15_mtf_15min** for **GAZPF**.
- **ROI:** 1.45%
- **Sharpe:** 4.26
- **Max Drawdown:** 0.19%

### Strategy Configuration
- **Confidence Threshold:** The current backtest used default settings. Consider optimizing `confidence_threshold` for higher precision.
- **Hybrid Approach:** Combining models via voting (Hybrid Ensemble) is recommended to smooth out volatility.
