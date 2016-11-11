# cabiPredict
Capital Bikeshare Predictions

This project is a demand and outage predictor for Capital Bikeshare. I take dock status and trip history, weather and calendar data, then fit a random forest regression model to estimate the customer demand for bikeshare as a function of ten predictors:
- Time of Day
- Day of Week
- Day of Year
- Holiday (Y/N)
- Year
- Air Temperature
- Relative Humidity
- Wind Speed
- Precipitation within the past hour
- Snow depth

I demonstrate this model with a customer-facing app that predicts CaBi demand and station outages in the immediate future. This app scrapes real-time dock status and weather data to form a feature vector, estimates customer demand for bikes and docks using the random forest, then computes outage probabilities with a Poisson model.
