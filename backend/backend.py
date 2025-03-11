from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime
import subprocess
import asyncio

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create uploads directory
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_latest_uploaded_file():
    """Get the most recently uploaded file from the uploads directory"""
    try:
        files = [os.path.join(UPLOAD_DIR, f) for f in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, f))]
        if not files:
            return None
        # Get the most recently modified file
        latest_file = max(files, key=os.path.getmtime)
        print("latest_file",latest_file)
        return {
            "path": latest_file,
            "timestamp": datetime.fromtimestamp(os.path.getmtime(latest_file)).isoformat()
        }
    except Exception as e:
        print(f"Error getting latest file: {e}")
        return None

# Initialize latest model with the most recent file
latest_model = get_latest_uploaded_file() or {
    "path": "",
    "timestamp": datetime.now().isoformat()
}

async def run_processing_script(file_path):
    """Run the processing script on the model file"""
    try:
        # You can replace this with your actual script path and parameters
        script_path = "scripts/get_body_dim.js"  # or any other script you want to run
        print(f"Running processing script on: {file_path}")
        
        # Run Node.js script
        process = await asyncio.create_subprocess_exec(
            'node', script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if stdout:
            print(f'Script output: {stdout.decode()}')
        if stderr:
            print(f'Script errors: {stderr.decode()}')
            
        return process.returncode == 0
    except Exception as e:
        print(f"Error running processing script: {e}")
        return False

@app.get("/latest-model-info")
async def get_latest_model_info():
    global latest_model
    current_latest = get_latest_uploaded_file()
    if current_latest and current_latest["path"] != latest_model["path"]:
        latest_model = current_latest
    return latest_model

@app.get("/static-model")
async def get_static_model():
    global latest_model
    current_latest = get_latest_uploaded_file()
    print("in statitic model",current_latest)
    
    if current_latest and os.path.exists(current_latest["path"]):
        # Update latest_model if there's a new file
        if current_latest["path"] != latest_model["path"]:
            latest_model = current_latest
        
        # Run the processing script
        print("before calling run_processing_script")
        await run_processing_script(current_latest["path"])
        
        # Determine media type based on file extension
        file_ext = os.path.splitext(current_latest["path"])[1].lower()
        media_type = {
            '.glb': 'model/gltf-binary',
            '.gltf': 'model/gltf+json',
            '.obj': 'model/obj',
        }.get(file_ext, 'application/octet-stream')
        
        return FileResponse(
            current_latest["path"],
            media_type=media_type,
            filename=os.path.basename(current_latest["path"]),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Last-Modified": current_latest["timestamp"]
            }
        )
    return {"error": "No model file found"}, 404

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # Always save as avatar.fbx
        file_path = os.path.join(UPLOAD_DIR, "avatar.fbx")
        
        # Remove existing file if it exists
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Save the new file
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Update latest model info
        global latest_model
        latest_model = {
            "path": file_path,
            "timestamp": datetime.now().isoformat()
        }
        
        print(f"New model saved as: {file_path}")
        
        return {
            "filename": "avatar.fbx",
            "size": len(content),
            "status": "processed",
            "timestamp": latest_model["timestamp"]
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {"error": str(e)}, 500

@app.get("/")
async def root():
    return {"message": "Backend is running"}

if __name__ == "__main__":
    print("Starting server at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)