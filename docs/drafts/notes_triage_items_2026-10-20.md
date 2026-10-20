# CAMARF items from Ross's notes (2026-10-20) -- for status check and triage

Source: a long paste of Ross's accumulated notes (health items excluded at his request; personal/admissions items
and another project's machine details excluded). One line per distinct CAMARF item, numbered for reference.

1. Study topics: optimization, measure theory, time series, probability theory, statistics
2. Integrate option pricing methods (Black-Scholes, binomial/trinomial trees) for comparison
3. Heat map of risk-management strategies and position-sizing methods with their results
4. Regime-dependent risk sizing
5. Black-swan events and circuit breakers
6. Backtesting through cross-validation (CPCV / purged k-fold)
7. Sharpe as a function of the number of independent bets (fundamental law / breadth)
8. Asset-characteristics analyzer: which characteristics are shared by assets with positive results
9. Portfolio comparisons: tangency, minimum variance, hierarchical risk parity, minimum CVaR
10. Stock valuation model correlation
11. Correlation of assets to macro events (FRED)
12. Lead-lag system (not cointegrated contemporaneously, but one leads the other)
13. Gaussian and Clayton copulas
14. Lou & Polk (2022) comomentum -- copy what works
15. Options features for ML: options flow, 0DTE, IV surface, net gamma exposure, open interest, vanna flow, convexity, delta-gamma Taylor expansion
16. Longin & Solnik (2001) extreme correlation
17. CFTC COT
18. Prime brokerage data
19. Dealer gamma
20. Donchian channels as ML features
21. "Johns Hopkins HLPPL model" (identity unknown)
22. Charm surface, volatility smile
23. Correlations of assets with interest rates; premium flows
24. Regimes in which assets correlate best
25. Regimes that give the best entries
26. HMMs / GMMs on individual ML factors to find convergence/divergence
27. Markov transition matrices
28. Entropy
29. Singha: hidden order in trades predicts the size of price moves
30. Full STORM review; full bug/function sweep; full pipeline diagnosis and run
31. Universe: add NASDAQ, Russell 2000, Dow; Asia and London session assets; more futures, commodities, crypto
32. Decoupling (relationships that come apart)
33. GitHub appearance: repo organization, clean-up, About section, professional checklist
34. STORM scores to 10/10 with real evidence, aware of the other side
35. Inverse correlation / polar-opposite equilibrium
36. Lookahead: every rolling window trailing only (PIT) -- every concept
37. Filter-attrition bias: how each filter (alone and combined) changes which pairs are found
38. Crowding detection: are other quants arbitraging the same signal
39. Use the project to answer open questions in the literature
40. Real-time position / standing measurement
41. Slippage and transaction-cost modelling
42. CLAUDE.md: honest, ethical, methodologically fair, reproducible process
43. Data test range documented so anyone can pull it
44. Guide for others to modify / validate the project
45. Fragile markets: Kritzman, Li, Page & Rigobon (2011) absorption ratio
46. Covariance implementation
47. Per-author deep dive; professors and research from top-50 universities and target schools
48. Market micro/macrostructure evolution: strategy decay by era, predicting future structure
49. Separate bug log from Development.md
50. Brownian motion, Fourier transform, Taylor series
51. Authors: Wilmott, Timothy Masters, Jim Simons, Robert Carver, Antti Ilmanen, Lopez de Prado, Peter Muller, Ed Thorp, Ernest Chan
52. Organize concepts into gap-fillers vs competitors; replica comparison tables; combine ideas
53. Log returns
54. last30days plugin
55. Paper section comparing findings with other papers (convergence / divergence)
56. Nagel (2025) / Buncic (2025) vs Kelly & Malamud (2025); Kelly, Malamud & Zhou (2024); Gu, Kelly & Xiu (2020)
57. Karpathy autoresearch; researchpooler
58. DeMiguel, Garlappi & Uppal (2009) 1/N; convex mean-variance / Sharpe / Sortino optimization
59. Data-hygiene and bias literature; code review against it; GitHub guides; psychology in finance/ML
60. Graphify; Obsidian for the codebase; awesome-claude-code
61. Papers: algorithmic market making with hedging and impact; Blitz et al. short-term signals; network momentum across asset classes; stat-arb in jump-diffusion with compound Poisson; Stoikov micro-price
62. Trade count 1,500 -> 2,200: portfolio-level capital-constrained test
63. GGR distance method and a fresh holdout window
64. Compounding: risk sized on point-in-time equity (1% of current equity)
65. Paper style: no "option A", no first/second/third person, no Ross's name
66. Is lead-lag used anywhere?
67. Question market structure in every claim; accommodate every caveat
68. Test portfolio risk-management strategies (even outside the paper)
69. report.py: more visuals
70. STORM (incl. Stanford STORM) scrutiny, one agent at a time
71. Compare findings with other papers
72. Karpathy-style LLM council
73. Plugins/skills/MCP usage guide; /doctor
74. Wavelet transforms
75. KO/PEP "should be cointegrated" -- what is being measured
76. Cointegrating other variables / factors; cointegration of cointegrations; wavelets or regimes; correlation instead
77. Code reviewer across the whole codebase
78. Verify every claim (Development, FINDINGS, research, paper)
79. Books: Hull, Wilmott, Zuckerman, Harris, Aronson, The Janus Factor
80. Expected value, conditional probability, Bayes, LLN, CLT, variance/covariance in the portfolio
81. report.py: portfolio vs buy-and-hold S&P 500; alpha and beta
82. Model comparison: XGBoost, LightGBM, ridge/lasso, random forest; LSTM and attention
83. Agentic workflow as graphs (Steinberger); Hermes agent
84. Monte Carlo on every number; which tests matter for results
85. A novel research subfield
86. Apply existing concepts to many metrics (price, beta, alpha, greeks...)
87. Normal vs shorter lengths for K-means / regime windows
88. Premortem skill (adapt)
89. WRDS TAQ instead of yfinance for intraday
90. Heikin-Ashi candles
91. Statistical jump models (Shu, Yu & Mulvey 2024; Bemporad et al. 2018); Hamilton (1989)
92. Efficient frontier; GBM paths; Monte Carlo option pricing with antithetic variates; 95% VaR; Bayesian thinking
93. Vectorized code
94. WRDS non-commercial licence compliance; data leakage
95. How top funds profit from others' strategy mistakes
96. polars, ruff, pandera
97. Automation; cheaper/more efficient pipeline
98. Overnight script that runs every file and writes results verbatim
99. Hardware: native ARM64, QNN NPU, WinML; hardware/software transparency; enable/disable docs
100. Ito, martingales, HJM, Malliavin, Levy processes, rough volatility, Haar; wavelet convergence/divergence
101. Significance of gamma and other greeks in ML/backtest
102. SVM trained by gradient descent
103. awesome-systematic-trading repo
104. More tickers
105. ML to identify cycles within an asset, cross-asset and cross-timeframe
106. huggingface.co/mito0o852
107. K-means, GMM, HMM, XGBoost, random forest, deep learning tuned without overfitting
108. Inverse variance/covariance/correlation/cointegration matrix in [-1, 1], polar-opposite mean reversion
109. Instruction audit (CLAUDE.md, rules, skills, hooks, memory)
110. Which Claude model / effort for the project on Pro
111. Full error-search plan; all docs current; failure handling if one part fails
112. optionsdx, dolthub, kaggle, CBOE; ridge regression
113. Update the repo description (it still says "full S&P 500")
114. Books: ML-based pairs trading, Flash Boys, ML for Algorithmic Trading, Mathematics of Financial Derivatives, Detecting Regime Changes in Computational Finance
115. Grep Development.md for scoped-not-built / out-of-date items
116. gs-quant replication with WRDS; Bongiorno & Challet (2024) covariance filtering; tf-quant-finance; QuantLib Heston; arch; SVI
117. public-apis list
118. prompt-master, playwright-mcp, serena, wshobson/agents
119. Monte Carlo options model; information-fusion (speed of pricing-in); libraries: quantlib, cvxpy, scikit-learn, pytorch, jax, pyarrow, polars, arch, vectorbt, pyportfolioopt, hftbacktest, zipline, kalshi market maker, tensortrade, nautilus trader
120. Synthetic Monte Carlo bars from the higher-timeframe direction
121. Helgoland (Rovelli)
122. Reproducibility: WRDS pricing disclaimer, can't share files, scripts to fetch; CONTRIBUTING; README; About
123. Breeden-Litzenberger risk-neutral density; backtest-overfitting detector
124. addyosmani/agent-skills; ian-xiaohei-illustrations; arXiv 2603.28052; ponytail
125. Task list of ~20 high-impact items; /goal
126. AUC, boosting, logistic regression, NN, kNN, SVM; distribution fits (normal ... Weibull, negative binomial)
127. Apply concepts to further metrics (deep dive)
128. Full code review; Development sweep; citations accurate
129. Internal consistency of every document, rules and citations
130. Academic process paper from the development log
131. Hawkes process; the scientific method
132. Google TimesFM; "Blue Book" data; financial reports for trade signals
133. Area under the curve of volatility-standardized metrics; sequences / monotone convergence
