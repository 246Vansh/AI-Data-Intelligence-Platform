from pathlib import Path
import pandas as pd

def load_csv(file_path: str | Path) -> pd.DataFrame:
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found {path}")
    
    if path.suffix.lower() != ".csv":
        raise ValueError(f"only csv files are currently supported")
    
    df = pd.read_csv(path)
    
    return df