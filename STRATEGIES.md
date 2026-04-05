# Example strategies (natural language)

Use any of these as `--strategy "..."` or in a file with `--strategy-file`. Strategies 1-80 use historical OHLCV data. Strategies 81-110 also use corporate events (earnings, dividends, splits) which are auto-detected and fetched.

---

## Trend and momentum

1. **SMA crossover with acceleration filter**  
   Buy when SMA 20 crosses above SMA 50 and the acceleration of SMA 20 is in the top 20% of its whole-history distribution. Sell when SMA 20 crosses below SMA 50.

2. **RSI oversold with MACD confirmation**  
   Buy when RSI is below 30 and MACD line crosses above the signal line on the same bar. Sell when RSI goes above 70 or when MACD crosses below the signal line.

3. **Dual moving average with trend strength**  
   Buy when the fast EMA (12) is above the slow EMA (26) and the rate of change of the fast EMA over the last 5 days is positive and in the top 30% of all 5-day ROC values in the history. Sell when the fast EMA crosses below the slow EMA.

4. **Bollinger mean reversion with RSI filter**  
   Buy when price touches or goes below the lower Bollinger band and RSI is below 40. Sell when price touches or goes above the upper Bollinger band or when RSI exceeds 60.

5. **MACD histogram momentum**  
   Buy when the MACD histogram turns from negative to positive and the histogram value is in the bottom 25% of all positive histogram values in the history (strong reversal). Sell when the histogram turns from positive to negative.

---

## Volatility and breakout

6. **ATR breakout with volume**  
   Buy when the close is above the highest high of the last 20 days and the current bar’s range (high minus low) is greater than 1.5 times the 14-period ATR and volume is above the 20-day average volume. Sell when the close is below the lowest low of the last 10 days.

7. **Bollinger squeeze**  
   Buy when the distance between the upper and lower Bollinger bands (as a fraction of the middle band) is in the bottom 10% of its whole history and then price closes above the middle band. Sell when price closes below the 20-day SMA.

8. **Stochastic with trend filter**  
   Buy when the slow stochastic %K crosses above %D in the oversold region (below 20) and the 50-day SMA is sloping up (today’s SMA 50 is greater than SMA 50 from 5 days ago). Sell when %K crosses below %D in the overbought region (above 80).

---

## Percentile and ranking

9. **RSI in bottom quintile with volume**  
   Buy when RSI is in the bottom 20% of all RSI values in the history and volume is in the top 30% of all volume values. Sell when RSI reaches the top 20% of its history or when price falls 3% from the entry (use close-to-close for simplicity).

10. **Price relative to its own range**  
    Buy when the close is in the bottom 15% of the 52-week high-low range and the 5-day rate of change of the close is positive. Sell when the close is in the top 15% of the 52-week range.

11. **Acceleration in top decile**  
    Buy when the 20-day SMA is above the 50-day SMA and the 3-day acceleration of the 20-day SMA (second difference) is in the top 10% of all such accelerations in the history. Sell when the 20-day SMA crosses below the 50-day SMA.

---

## Multi-timeframe style (same history, different windows)

12. **Short and medium trend alignment**  
    Buy when the 10-day SMA is above the 20-day SMA and the 20-day SMA is above the 50-day SMA and the close is above all three. Sell when the close is below the 10-day SMA.

13. **Momentum consistency**  
    Buy when the 5-day, 10-day, and 20-day rates of change of the close are all positive and RSI is between 40 and 70 (not overbought). Sell when any of the three ROC values turns negative or RSI goes above 75.

---

## Mean reversion

14. **Distance from VWAP**  
    Buy when the close is more than 2 ATRs below the daily VWAP (or the rolling 20-day VWAP) and RSI is below 35. Sell when the close is above VWAP or RSI exceeds 65.

15. **Bollinger reversion with ADX**  
    Buy when price is below the lower Bollinger band and ADX is below 25 (weak trend). Sell when price returns to the middle band or ADX rises above 30.

---

## Crossover with confirmation

16. **EMA crossover with volume spike**  
    Buy when the 12-period EMA crosses above the 26-period EMA and volume is at least 1.5 times the 20-day average volume. Sell when the 12-period EMA crosses below the 26-period EMA.

17. **Williams %R and CCI confluence**  
    Buy when Williams %R is below minus 80 and CCI is below minus 100. Sell when Williams %R is above minus 20 or CCI is above 100.

18. **Stochastic RSI double oversold**  
    Buy when the Stochastic RSI (if available) or the standard RSI is below 25 and the slow stochastic %K is below 20. Sell when RSI is above 60 or %K is above 80.

---

## Custom logic

19. **Volatility contraction then expansion**  
    Buy when the 20-day ATR as a percentage of the 20-day SMA is in the bottom 20% of its history and then the next bar’s close is above the previous bar’s high. Sell when the 5-day ATR exceeds the 20-day ATR by 20% or when price closes below the 10-day SMA.

20. **Three-bar pattern**  
    Buy when the close is higher than the open for three consecutive bars and each bar’s close is higher than the previous bar’s close and volume is increasing over the three bars. Sell when the close is lower than the open and the close is below the low of the previous bar.

---

## More complex strategies (20 additional)

21. **Triple-trend alignment with momentum**  
    Buy when the 5-day EMA is above the 20-day EMA, the 20-day EMA is above the 50-day EMA, the close is above all three, and the 10-day rate of change of the close is in the top 25% of its history. Sell when the close crosses below the 20-day EMA or the 5-day EMA crosses below the 20-day EMA.

22. **RSI divergence-style pullback**  
    Buy when price makes a higher low (today’s low is above the low of 5 days ago) and RSI is between 30 and 45 and the 20-day SMA is sloping up (today’s SMA 20 is greater than SMA 20 from 3 days ago). Sell when RSI exceeds 70 or price closes below the 20-day SMA.

23. **Bollinger band width percentile with breakout**  
    Buy when the Bollinger band width (upper minus lower as a fraction of the middle band) has been in the bottom 15% of its history for at least 3 consecutive bars and then the close breaks above the upper band. Sell when the close returns inside the bands or falls below the 10-day SMA.

24. **MACD zero-line cross with volume and RSI**  
    Buy when the MACD line crosses above zero and the MACD histogram is positive and RSI is between 45 and 65 and volume is above the 10-day average volume. Sell when the MACD line crosses below zero or RSI goes above 75.

25. **Multi-window momentum confluence**  
    Buy when the 5-day, 10-day, and 20-day rates of change of the close are all positive, the 20-day SMA is above the 50-day SMA, and the close is above the 20-day SMA. Sell when any of the three ROC values turns negative or the close falls below the 20-day SMA.

26. **Volatility regime filter with mean reversion**  
    Buy when the 14-period ATR as a percentage of the close is in the top 30% of its history (high volatility) and price touches or goes below the lower Bollinger band and RSI is below 35. Sell when price touches the middle Bollinger band or RSI exceeds 60.

27. **Stochastic and RSI double confirmation**  
    Buy when the slow stochastic %K crosses above %D while both are below 30, and RSI crosses above 30 on the same bar, and the close is above the 50-day SMA. Sell when %K crosses below %D above 70 or when the close falls below the 50-day SMA.

28. **VWAP distance with trend and RSI**  
    Buy when the close is more than 1.5 times the 14-period ATR below the rolling 20-day VWAP, and the 50-day SMA is above the 50-day SMA from 10 days ago, and RSI is below 40. Sell when the close is above VWAP or RSI exceeds 65.

29. **Acceleration and ROC in top quintile**  
    Buy when the 20-day SMA is above the 50-day SMA, the 3-day acceleration of the 20-day SMA is in the top 20% of its history, and the 5-day rate of change of the close is in the top 20% of its history. Sell when the 20-day SMA crosses below the 50-day SMA.

30. **Williams %R, CCI, and RSI triple oversold**  
    Buy when Williams %R is below minus 90, CCI is below minus 150, and RSI is below 30. Sell when Williams %R rises above minus 20 or CCI rises above 50 or RSI exceeds 65.

31. **ADX trend strength with EMA crossover**  
    Buy when the 12-period EMA crosses above the 26-period EMA and ADX is above 25 and rising (today’s ADX is greater than ADX from 3 days ago). Sell when the 12-period EMA crosses below the 26-period EMA or ADX falls below 20.

32. **Volume-weighted momentum**  
    Buy when the close is above the 20-day SMA, the 10-day rate of change of the close is positive, and the 5-day average volume is in the top 25% of all 5-day average volume values in the history. Sell when the close falls below the 20-day SMA or the 10-day ROC turns negative.

33. **Price and ATR in range percentiles**  
    Buy when the close is in the bottom 20% of its 50-day high-low range and the 14-period ATR as a fraction of the 50-day high-low range is in the bottom 25% of that ratio’s history. Sell when the close is in the top 20% of its 50-day range.

34. **Three-SMA stack with close confirmation**  
    Buy when the 8-day SMA is above the 21-day SMA and the 21-day SMA is above the 55-day SMA and the close is above the 8-day SMA and volume is above the 20-day average. Sell when the close is below the 8-day SMA.

35. **Bollinger and RSI with trend filter**  
    Buy when price is below the lower Bollinger band, RSI is below 35, and the 50-day SMA is above the 50-day SMA from 5 days ago. Sell when price touches the middle band or RSI exceeds 60.

36. **MACD histogram percentile reversal**  
    Buy when the MACD histogram crosses from negative to positive and the new positive histogram value is in the bottom 20% of all positive histogram values in the history, and the close is above the 50-day SMA. Sell when the histogram crosses from positive to negative.

37. **Consecutive higher closes with volume**  
    Buy when the close is higher than the previous close for four consecutive bars and the sum of volume over those four bars is in the top 30% of all 4-day volume sums in the history. Sell when the close is lower than the open and lower than the previous bar’s low.

38. **Dual ATR volatility expansion**  
    Buy when the 5-day ATR has been below the 20-day ATR for at least 3 consecutive bars and then the current bar’s range (high minus low) exceeds 1.5 times the 20-day ATR and the close is above the open. Sell when the close is below the 10-day SMA or the 5-day ATR exceeds the 20-day ATR by 30%.

39. **RSI and stochastic zone confluence**  
    Buy when RSI is between 25 and 40 and the slow stochastic %K is between 15 and 35 and the 20-day SMA is above the 50-day SMA. Sell when RSI exceeds 65 or %K exceeds 80.

40. **Rate of change of volatility**  
    Buy when the 20-day ATR as a percentage of the 20-day SMA is in the bottom 15% of its history and the 5-day rate of change of that same ratio is positive (volatility starting to expand). Sell when that ATR-percent ratio exceeds its 20-day rolling 80th percentile or price closes below the 20-day SMA.

---

## Even more complex strategies (20 additional)

41. **Four-EMA stack with volume and RSI**  
    Buy when the 5-day EMA is above the 10-day EMA, the 10-day is above the 20-day, the 20-day is above the 50-day, the close is above the 5-day EMA, RSI is between 50 and 70, and volume is above the 15-day average. Sell when the close crosses below the 10-day EMA or RSI exceeds 75.

42. **Bollinger width expansion after squeeze**  
    Buy when the Bollinger band width (upper minus lower divided by middle band) has been below its 20-day 20th percentile for at least 3 bars and then crosses above its 20-day 50th percentile and the close is above the middle band. Sell when the close falls below the 20-day SMA or the width falls back below its 20-day 30th percentile.

43. **RSI and MACD histogram double bottom**  
    Buy when RSI makes a higher low (today’s RSI is above RSI from 5 days ago) while RSI is between 25 and 45, and the MACD histogram is positive and greater than the histogram from 3 days ago. Sell when RSI exceeds 70 or the MACD histogram turns negative.

44. **Stochastic and CCI oversold with trend**  
    Buy when the slow stochastic %K is below 25 and CCI is below minus 120 and the 20-day SMA is above the 20-day SMA from 5 days ago. Sell when %K rises above 75 or CCI rises above 50.

45. **Price and volume in dual percentiles**  
    Buy when the close is in the bottom 25% of its 30-day high-low range and the 5-day average volume is in the top 25% of all 5-day average volumes in the history and the 5-day rate of change of the close is positive. Sell when the close is in the top 25% of its 30-day range.

46. **ATR and Bollinger band confluence**  
    Buy when the close is below the lower Bollinger band, the 14-period ATR as a percentage of the close is in the top 25% of its history, and RSI is below 40. Sell when the close touches or crosses above the middle band or RSI exceeds 65.

47. **EMA ribbon with momentum filter**  
    Buy when the close is above the 8-day, 13-day, and 21-day EMAs, the 8-day EMA is above the 13-day and the 13-day is above the 21-day, and the 10-day rate of change of the close is in the top 30% of its history. Sell when the close crosses below the 8-day EMA.

48. **VWAP and ATR pullback**  
    Buy when the close is between 0.5 and 1.5 times the 14-period ATR below the rolling 20-day VWAP, the 50-day SMA is sloping up (today greater than 5 days ago), and RSI is between 28 and 42. Sell when the close is above VWAP or RSI exceeds 68.

49. **MACD and stochastic trend alignment**  
    Buy when the MACD line is above the signal line, the MACD histogram is positive, the slow stochastic %K is above %D and both are between 40 and 70, and the close is above the 50-day SMA. Sell when the MACD line crosses below the signal line or %K crosses below %D above 80.

50. **Consecutive lower highs with RSI**  
    Buy when the high is lower than the high of 3 days ago for two consecutive bars and RSI is between 35 and 50 and the 20-day SMA is above the 50-day SMA. Sell when RSI exceeds 70 or the close falls below the 20-day SMA.

51. **Williams %R and ADX oversold**  
    Buy when Williams %R is below minus 85, ADX is above 20 (trend present), and the close is above the 50-day SMA. Sell when Williams %R rises above minus 25 or the close falls below the 50-day SMA.

52. **Rate of change of RSI**  
    Buy when RSI is between 30 and 45 and the 5-day rate of change of RSI is positive and in the top 30% of all such 5-day RSI changes in the history. Sell when RSI exceeds 65 or the 5-day ROC of RSI turns negative.

53. **Three-SMA slope alignment**  
    Buy when the 10-day, 20-day, and 50-day SMAs are all sloping up (each is greater than its value 5 days ago) and the close is above all three and the 5-day ROC of the close is positive. Sell when the close crosses below the 10-day SMA.

54. **Bollinger and volume spike**  
    Buy when the close touches or pierces the lower Bollinger band and the current bar’s volume is in the top 20% of all bar volumes in the history and RSI is below 45. Sell when the close touches the middle band or RSI exceeds 60.

55. **Dual time frame ROC**  
    Buy when the 5-day rate of change of the close is positive, the 20-day rate of change of the close is positive, and both are in the top 40% of their respective full-history distributions. Sell when either ROC turns negative or the close falls below the 20-day SMA.

56. **EMA cross with histogram confirmation**  
    Buy when the 12-period EMA crosses above the 26-period EMA and on the same bar the MACD histogram is positive and the close is above the 26-period EMA. Sell when the 12-period EMA crosses below the 26-period EMA.

57. **Range and volatility contraction**  
    Buy when the 20-day high-low range as a fraction of the 20-day SMA is in the bottom 15% of that ratio’s history and the close is above the 20-day SMA and the 5-day ROC of the close is positive. Sell when that range ratio exceeds its 20-day 70th percentile or the close falls below the 20-day SMA.

58. **RSI and Bollinger position**  
    Buy when RSI is between 30 and 50 and the close is in the bottom 30% of the distance between the lower and upper Bollinger bands (measured from lower to upper). Sell when RSI exceeds 65 or the close is in the top 30% of that band distance.

59. **Volume trend with price breakout**  
    Buy when the close is above the highest high of the last 15 days and the 10-day average volume is above the 30-day average volume and the 10-day ROC of volume is positive. Sell when the close is below the lowest low of the last 10 days.

60. **Composite momentum score**  
    Buy when the 5-day ROC of the close is positive, the 10-day ROC is positive, RSI is between 45 and 65, and the MACD line is above the signal line. Sell when any of the two ROCs turns negative or RSI exceeds 72 or the MACD line crosses below the signal line.

---

## Multi-timeframe strategies (intraday, hourly, weekly, monthly)

61. **5-minute RSI scalp with VWAP filter**  
    On 5-minute bars, buy when RSI(10) drops below 25 and the close is below VWAP and the current bar's volume is above the 20-bar average volume. Sell when RSI(10) rises above 60 or the close crosses above VWAP.

62. **15-minute Bollinger squeeze breakout**  
    On 15-minute candles, buy when the Bollinger band width (upper minus lower divided by middle) has been in the bottom 10% of its history for at least 5 consecutive bars and then the close breaks above the upper band with volume above the 30-bar average. Sell when the close falls below the middle band or the band width returns to the bottom 10% again.

63. **Hourly MACD and EMA ribbon trend follower**  
    On hourly data, buy when the 8-period EMA is above the 21-period EMA and the 21-period is above the 55-period EMA and the MACD histogram is positive and increasing (current histogram greater than previous bar's histogram) and RSI is between 45 and 70. Sell when the 8-period EMA crosses below the 21-period EMA or RSI exceeds 78.

64. **30-minute stochastic mean reversion with ATR bands**  
    On 30-minute bars, buy when the slow stochastic %K is below 15 and CCI is below minus 150 and the close is more than 1.5 times the 14-period ATR below the 50-bar SMA. Sell when %K rises above 70 or the close returns above the 50-bar SMA.

65. **5-minute VWAP bounce with momentum confirmation**  
    On 5-minute candles, buy when the close crosses above VWAP from below and the 5-bar rate of change of the close is positive and in the top 30% of all 5-bar ROC values in the session history, and volume on the current bar is at least 1.5 times the 20-bar average. Sell when the close falls more than 0.5 times the 14-period ATR below VWAP or RSI(10) exceeds 75.

66. **Hourly triple indicator confluence**  
    On 1-hour data, buy when RSI(14) is between 30 and 50 and the MACD line is above the signal line and the slow stochastic %K is below 40 and the close is above the 50-bar SMA. Sell when RSI exceeds 70 or %K crosses below %D above 75 or the MACD line crosses below the signal line.

67. **Weekly momentum rotation**  
    On weekly bars, buy when the 4-week rate of change of the close is positive and in the top 25% of its whole history and the 10-week SMA is above the 30-week SMA and RSI(14) is between 50 and 70. Sell when the 4-week ROC turns negative or the 10-week SMA crosses below the 30-week SMA.

68. **Monthly trend and volatility regime**  
    On monthly candles, buy when the close is above the 10-month SMA and the 12-month rate of change of the close is positive and the 6-month ATR as a percentage of the close is in the bottom 40% of its history (low volatility regime). Sell when the close falls below the 10-month SMA or the 12-month ROC turns negative.

69. **15-minute volume-weighted breakout with ADX**  
    On 15-minute data, buy when the close breaks above the highest high of the last 40 bars and ADX is above 25 and rising (current ADX greater than ADX from 5 bars ago) and the current bar's volume is in the top 20% of all bar volumes in the history. Sell when the close falls below the lowest low of the last 20 bars or ADX drops below 20.

70. **5-minute dual EMA scalp with ATR trailing stop**  
    On 5-minute bars, buy when the 9-period EMA crosses above the 21-period EMA and the close is above both and the 14-period ATR is in the bottom 40% of its history (low volatility, potential breakout). Sell when the close falls more than 2 times the 14-period ATR below the entry price or the 9-period EMA crosses below the 21-period EMA.

71. **Hourly Bollinger and RSI mean reversion with volume spike**  
    On hourly candles, buy when the close is below the lower Bollinger band (20-period, 2 std dev) and RSI(14) is below 30 and the current bar's volume is at least 2 times the 50-bar average volume and the 200-bar SMA is sloping up (current value greater than 20 bars ago). Sell when the close crosses above the middle Bollinger band or RSI exceeds 60.

72. **30-minute Williams %R and CCI double oversold with trend**  
    On 30-minute data, buy when Williams %R(14) is below minus 90 and CCI(20) is below minus 180 and the 100-bar SMA is above the 100-bar SMA from 10 bars ago. Sell when Williams %R rises above minus 30 or CCI rises above zero.

73. **Weekly Bollinger width percentile breakout**  
    On weekly bars, buy when the Bollinger band width has been in the bottom 15% of its history for at least 2 consecutive weeks and then the close breaks above the upper band and volume is above the 10-week average. Sell when the close falls below the middle band or the band width falls back into the bottom 15%.

74. **Hourly multi-indicator momentum stack**  
    On 1-hour candles, buy when the 20-bar SMA is above the 50-bar SMA and ADX is above 30 and the MACD histogram is positive and increasing for 3 consecutive bars and RSI is between 50 and 68 and OBV is above its 20-bar SMA. Sell when ADX drops below 22 or the MACD histogram turns negative or RSI exceeds 75.

75. **Monthly relative strength with moving average**  
    On monthly data, buy when the close is above both the 6-month and 12-month SMAs and the 3-month rate of change of the close is in the top 30% of its whole history and the 6-month SMA is above the 12-month SMA. Sell when the close falls below the 6-month SMA or the 3-month ROC turns negative.

76. **15-minute consecutive narrow range then expansion**  
    On 15-minute bars, buy when the bar range (high minus low) has been below 0.8 times the 20-bar ATR for at least 3 consecutive bars and then the current bar's range exceeds 1.2 times the 20-bar ATR and the close is above the open and volume is above the 20-bar average. Sell when the close falls below the 50-bar SMA or the 5-bar ATR exceeds the 20-bar ATR by 30%.

77. **5-minute OBV divergence with RSI**  
    On 5-minute candles, buy when the close makes a lower low compared to 10 bars ago but OBV makes a higher low compared to 10 bars ago (bullish divergence) and RSI(10) is between 25 and 45. Sell when RSI exceeds 65 or the close falls below the lowest low of the last 20 bars.

78. **Hourly price channel breakout with stochastic filter**  
    On hourly data, buy when the close breaks above the highest high of the last 50 bars and the slow stochastic %K is between 50 and 80 (confirming momentum without being overbought) and volume is above the 20-bar average. Sell when the close falls below the lowest low of the last 25 bars or %K drops below 20.

79. **Weekly ADX and EMA crossover for swing trades**  
    On weekly bars, buy when the 12-week EMA crosses above the 26-week EMA and ADX is above 20 and rising (current ADX greater than ADX from 2 weeks ago) and the MACD line is above the signal line. Sell when the 12-week EMA crosses below the 26-week EMA or ADX drops below 18.

80. **30-minute composite oversold with acceleration**  
    On 30-minute candles, buy when RSI(14) is below 35 and CCI(20) is below minus 100 and the slow stochastic %K is below 25 and the 3-bar acceleration of the 50-bar SMA (second difference) is positive (trend decelerating its descent). Sell when RSI exceeds 60 or %K exceeds 70 or the close rises above the 50-bar SMA.

---

## Corporate event strategies — earnings

81. **Pre-earnings momentum**  
    Buy 5 days before earnings and sell on the day of the earnings announcement. Only enter if the 20-day SMA is above the 50-day SMA at the time of entry.

82. **Post-earnings drift**  
    Buy on the day after earnings if the EPS surprise percentage is positive (actual beat estimate). Sell 10 trading days later or when RSI exceeds 70, whichever comes first.

83. **Earnings straddle exit**  
    Buy 3 days before earnings and sell 2 days after earnings. Use a stop loss: also sell if at any point the close falls more than 2 times the 14-day ATR below the entry price.

84. **Earnings surprise momentum**  
    Buy on the first trading day after an earnings announcement if the EPS surprise percentage is above 5 percent and the close is above the 20-day SMA. Sell when RSI exceeds 70 or 15 trading days after entry, whichever comes first.

85. **Fade the earnings gap**  
    Sell (go short) on the day after earnings if the stock gapped up (today's open is more than 1 percent above yesterday's close) and RSI is above 65. Buy to cover when RSI drops below 45 or when the close falls to the 20-day SMA.

86. **Earnings run-up with volume confirmation**  
    Buy 10 days before earnings if the 10-day average volume is in the top 30 percent of its full history and the 5-day rate of change of the close is positive. Sell on the day of earnings.

87. **Consecutive earnings beats**  
    Buy on the day after earnings if the EPS actual exceeded the EPS estimate (positive surprise) and the previous earnings also had a positive surprise. Sell 20 trading days later or when the close falls below the 50-day SMA.

88. **Earnings volatility contraction**  
    Buy 7 days before earnings if the 14-day ATR as a percentage of the close is in the bottom 25 percent of its history (volatility is unusually low heading into earnings). Sell 2 days after the earnings announcement.

---

## Corporate event strategies — dividends

89. **Ex-dividend capture**  
    Buy 3 days before an ex-dividend date and sell on the ex-dividend date itself. Only enter if the dividend amount is greater than zero and the 20-day SMA is sloping upward.

90. **Post ex-dividend recovery**  
    Buy on the ex-dividend date (when the stock typically drops by the dividend amount) and sell 5 trading days later, betting on a price recovery.

91. **High dividend with momentum**  
    Buy on the ex-dividend date if the dividend amount is in the top 25 percent of all dividend amounts in the history and the 10-day rate of change of the close is positive. Sell 10 days later or when RSI exceeds 65.

92. **Dividend and trend alignment**  
    Buy 5 days before the ex-dividend date if the 20-day SMA is above the 50-day SMA and RSI is between 40 and 60. Sell 3 days after the ex-dividend date.

---

## Corporate event strategies — stock splits

93. **Pre-split momentum**  
    Buy 10 days before a stock split and sell on the day of the split. Only enter if the 20-day SMA is above the 50-day SMA.

94. **Post-split continuation**  
    Buy on the day of a stock split if the split ratio is greater than 1 (forward split, not reverse) and the close is above the 20-day SMA. Sell 20 trading days later or when the close falls below the 20-day SMA.

---

## Hybrid strategies — corporate events with technical indicators

95. **Earnings and RSI oversold**  
    Buy when the stock is within 5 days of an earnings announcement and RSI is below 35 and the 50-day SMA is sloping upward. Sell 3 days after earnings or when RSI exceeds 65, whichever comes first.

96. **Post-earnings Bollinger breakout**  
    Buy on the day after earnings if the close is above the upper Bollinger band (20-period, 2 standard deviations) and the EPS surprise percentage is positive and volume is above the 20-day average. Sell when the close falls below the middle Bollinger band or 10 trading days after entry.

97. **Earnings run-up with MACD confirmation**  
    Buy 7 days before earnings if the MACD line is above the signal line and the MACD histogram is positive and the close is above the 50-day SMA. Sell on the day of the earnings announcement.

98. **Ex-dividend with Bollinger mean reversion**  
    Buy on the ex-dividend date if the close is below the middle Bollinger band (20, 2) and RSI(14) is below 50. Sell when the close rises above the upper Bollinger band or RSI exceeds 65.

99. **Earnings surprise with stochastic confirmation**  
    Buy on the first day after earnings if the EPS surprise percentage is above 3 percent and the slow stochastic %K is below 50 and rising (current %K is greater than %K from 2 days ago). Sell when %K exceeds 80 or 15 trading days after entry.

100. **Multi-event regime filter**  
     Buy when the stock is more than 15 days away from the next earnings date (stable regime) and RSI is below 35 and the close is below the lower Bollinger band and volume is above the 20-day average. Sell when RSI exceeds 60 or the stock is within 5 days of earnings (avoid holding through earnings).

---

## Multi-timeframe with corporate events

101. **Hourly earnings momentum scalp**  
     On hourly bars, buy when the stock is on an earnings day and the hourly RSI(10) drops below 30 and the close is below the 50-bar hourly SMA. Sell when hourly RSI exceeds 60 or the close rises above the 50-bar hourly SMA.

102. **Weekly earnings cycle with monthly trend**  
     On weekly bars, buy when the stock is within 2 weeks of an earnings date and the 10-week SMA is above the 30-week SMA and the 4-week rate of change of the close is positive. Sell 2 weeks after the earnings date or when the 10-week SMA crosses below the 30-week SMA.

103. **Hourly post-earnings breakout**  
     On hourly bars, buy on the day after an earnings announcement if the close breaks above the highest high of the last 40 bars and volume is above the 30-bar average. Sell when the close falls below the 50-bar SMA or RSI(10) exceeds 80.

104. **Hourly earnings day volatility scalp**  
     On hourly candles, buy on an earnings day when the close is more than 1.5 times the 14-period ATR below the 50-bar SMA and RSI(10) is below 25. Sell when the close returns above the 50-bar SMA or RSI(10) exceeds 65.

105. **Hourly pre-earnings accumulation with ADX**  
     On hourly data, buy when the stock is within 3 days of earnings and ADX is above 25 and rising and the close is above the 20-bar EMA and the MACD histogram is positive. Sell on the day of earnings or when ADX drops below 20.

---

## Advanced multi-indicator and multi-event strategies

106. **Earnings and dividend double catalyst**  
     Buy when the stock is within 10 days of an earnings date and also within 10 days of an ex-dividend date and the 20-day SMA is above the 50-day SMA and RSI is between 40 and 60. Sell 5 days after earnings or when the close falls below the 20-day SMA.

107. **Post-earnings drift with Bollinger and volume**  
     Buy on the day after earnings if the EPS surprise percentage is positive and volume is above its 20-day average. Sell when the close falls below the middle Bollinger band (20, 2) or 15 trading days after entry, whichever comes first.

108. **Earnings volatility regime with ATR percentile**  
     Buy 5 days before earnings if the 14-day ATR as a percentage of the close is in the bottom 20 percent of its history (unusually calm before earnings) and the 20-day SMA is above the 50-day SMA. Sell 3 days after earnings or if the 14-day ATR percentage jumps to the top 30 percent of its history.

109. **Dividend income with trend and volatility filter**  
     Buy 5 days before the ex-dividend date if the 50-day SMA is above the 200-day SMA (if enough data) or the 50-day SMA is above the 50-day SMA from 20 days ago, and the 14-day ATR as a percentage of the close is below its median. Sell on the ex-dividend date.

110. **Composite corporate and technical score**  
     Buy when at least two of the following conditions are true: the stock is within 7 days of earnings, RSI is below 40, the MACD line is above the signal line, and the close is above the 50-day SMA. Sell when RSI exceeds 65 or the close falls below the 50-day SMA or the stock is more than 20 days past earnings.

---

Copy a full sentence (or paragraph) into your run:

```bash
backtester run --strategy "Buy when SMA 20 crosses above SMA 50 and the acceleration of SMA 20 is in the top 20% of its whole-history distribution. Sell when SMA 20 crosses below SMA 50." --ticker AAPL --model openai
```

Or save one or more strategies to a text file and use `--strategy-file path/to/file.txt`.

For non-daily timeframes, either mention the timeframe in your strategy (e.g. "On 5-minute bars") and the CLI will auto-detect it, or pass `--interval 5m` explicitly:

```bash
backtester run --strategy "On 5-minute bars, buy when RSI drops below 25 and sell when RSI rises above 60" --ticker AAPL
backtester run --strategy "Weekly momentum rotation with SMA crossover" --ticker SPY --interval 1wk
```

For strategies involving corporate events (earnings, dividends, splits), the CLI auto-detects the keywords and fetches the relevant data:

```bash
backtester run --strategy "Buy 3 days before earnings announcement, sell 1 day after earnings" --ticker AAPL --model openai
backtester run --strategy "Buy on ex-dividend date if close is below lower Bollinger band and RSI below 40. Sell when close returns to middle band." --ticker MSFT
backtester run --strategy "Buy 5 days before earnings if ATR is low and trend is up. Sell 2 days after earnings." --ticker GOOGL
```
