# Nasdaq Volume Radar (Hacim Radarı)

An AI-assisted Python desktop market-data monitoring project. It aggregates streaming trade data into rolling time windows and visualizes changes in volume and trade flow. A simulated-data mode enables demonstration without live market credentials.

## Features

- Rolling 1-second, 1-minute and 5-minute trade volume calculations
- Relative volume and volume spike monitoring
- Estimated buy/sell pressure and net trade flow
- Tkinter desktop interface with configurable alerts
- Webull OpenAPI integration and simulated-data feed

## Project structure

- engine.py: thread-safe trade aggregation, simulated feed and Webull integration
- app.py: desktop interface and configuration
- config.example.json: example settings (no real API credentials)
- requirements.txt: Python dependencies
- KUR_VE_CALISTIR.bat: Windows setup and launcher
- EXE_YAP.bat: optional PyInstaller build script

## Getting started

Install Python 3.12 and dependencies from requirements.txt in a virtual environment, then run python app.py. Use the Demo button to explore the interface without connecting to Webull. Live mode requires approved API access and relevant market-data entitlement. Never commit your real config.json or token files.

## Limitations

Live Webull connectivity has not been independently verified; simulated data is not real market data. Trade-direction estimates are approximate. This project is for educational data visualization and software development, not investment advice or automated trading.
