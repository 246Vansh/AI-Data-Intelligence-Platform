import io
import os
import shutil
from data_engine.ingestion import ingest_to_parquet

# 1. Create a mock CSV binary stream in-memory
mock_csv_data = b"id,name,value\n1,Alpha,10.5\n2,Beta,20.0\n3,Gamma,35.2\n"
stream = io.BytesIO(mock_csv_data)

# 2. Setup a temporary storage directory
test_root = "./tmp_test_storage"
os.makedirs(test_root, exist_ok=True)
dataset_id = "test_run_001"

try:
    # 3. Execute ingestion
    result = ingest_to_parquet(stream, dataset_id, test_root)
    
    # 4. Assert invariants manually
    print("--- Ingestion Verification Successful ---")
    print(f"Target Path: {result.parquet_path}")
    print(f"Expected Rows: 3 | Parsed Rows: {result.row_count}")
    print(f"Expected Columns: ['id', 'name', 'value'] | Parsed Columns: {result.column_names}")
    
    assert result.row_count == 3, "Row count mismatch!"
    assert os.path.exists(result.parquet_path), "Parquet file was not written to disk!"
    print("✅ All local validation assertions passed.")

except Exception as e:
    print(f"❌ Validation Failed: {e}")
finally:
    # Clean up workspace
    if os.path.exists(test_root):
        shutil.rmtree(test_root)
