cd backend
source .venv/bin/activate

nohup uvicorn app:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
echo $! > backend.pid

echo "Backend corriendo en background, PID: $(cat backend.pid)"
cd ..