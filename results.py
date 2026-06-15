import pandas as pd, os

results_dir = r"output\results"
for tf in ["1m", "2m", "3m", "15m", "1h", "4h", "1D", "7D", "1M"]:
    path = os.path.join(results_dir, tf, "pairs.parquet")
    if os.path.exists(path):
        df = pd.read_parquet(path)
        print(f"\n{tf}:")
        print(
            df[
                [
                    "symbol_a",
                    "symbol_b",
                    "asset_class_a",
                    "asset_class_b",
                    "pearson_corr",
                    "coint_pvalue_adjusted",
                    "half_life_rolling",
                    "coint_fraction_rolling",
                ]
            ].to_string()
        )
