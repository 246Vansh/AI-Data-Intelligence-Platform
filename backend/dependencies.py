from pathlib import Path

from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data


DATASET_PATH = Path(
    "data/raw/Walmart_Sales.csv"
)


def get_walmart_data():
    df = load_csv(DATASET_PATH)

    df = clean_walmart_data(df)

    return df