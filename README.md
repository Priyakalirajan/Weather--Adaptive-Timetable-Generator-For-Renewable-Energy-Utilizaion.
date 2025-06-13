# Weather-Based Timetable Generator

A Flask web application that generates timetables based on weather conditions for optimal scheduling.

## Features

- Real-time weather data integration using OpenWeatherMap API
- Dynamic timetable generation based on weather conditions
- File upload and download functionality
- History tracking for uploaded and downloaded files
- Modern and responsive user interface
- Support for multiple timetable generation

## Prerequisites

- Python 3.8 or higher
- pip (Python package installer)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd weather-timetable-generator
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

1. Get an API key from [OpenWeatherMap](https://openweathermap.org/api)
2. Replace the `API_KEY` in `app.py` with your API key
3. Optionally, change the `CITY` variable in `app.py` to your desired location

## Usage

1. Start the Flask application:
```bash
python app.py
```

2. Open your web browser and navigate to:
```
http://localhost:5000
```

3. Follow the steps:
   - Check weather forecast
   - Upload your data file (CSV format)
   - Generate timetable
   - Download the results

## File Format

The input CSV file should have the following columns:
- Date (YYYY-MM-DD)
- Day
- Condition
- Temperature
- Humidity
- Wind Speed

Example:
```csv
Date,Day,Condition,Temperature,Humidity,Wind Speed
2024-03-20,Monday,Clear,28.5,65,3.2
2024-03-21,Tuesday,Cloudy,27.8,70,4.1
```

## Weather Impact on Schedule

- Clear Weather: Computer Lab activities
- Cloudy: Regular Class activities
- Rainy: Indoor activities
- Stormy: No outdoor activities

## Project Structure

```
weather-timetable-generator/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── README.md             # This file
├── templates/            # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── weather.html
│   ├── upload.html
│   ├── output.html
│   ├── view.html
│   └── downloads.html
├── uploads/              # Uploaded files
└── downloads/           # Generated files
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.