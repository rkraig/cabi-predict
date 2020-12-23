# cabi-predict

## Capital Bikeshare: Predictions of Near-Term Supply and Demand

This project is a demand and outage predictor for Capital Bikeshare. I take dock status and trip history, weather and calendar data, then fit a random forest regression model to estimate the customer demand for bikes and docks at each bikeshare station as a function of ten predictors:
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

I demonstrate this model with a customer-facing app that predicts CaBi demand and station outages in the immediate future. This app scrapes real-time dock status and weather data to form a feature vector, estimates customer demand for bikes and docks using the random forest, then computes outage probabilities with a Poisson model. Predictions are visualized on a map using leaflet.js. Result is published to a web app using Flask, hosted on heroku.

## App

https://cabi-predict.herokuapp.com/

(Update: I see that the leaflet.js map of prediction output data has broken on heroku... I have not investigated or fixed that yet.)

