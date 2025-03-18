import os
import json
import uvicorn
import asyncio
from datetime import datetime
import subprocess
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from scripts.sizing_recommendation.sizing_recommender import get_size

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_latest_uploaded_file():
    """Get the most recently uploaded file from the uploads directory."""
    try:
        files = [
            os.path.join(UPLOAD_DIR, f)
            for f in os.listdir(UPLOAD_DIR)
            if os.path.isfile(os.path.join(UPLOAD_DIR, f))
        ]
        if not files:
            return None
        latest_file = max(files, key=os.path.getmtime)
        print("latest_file", latest_file)
        return {
            "path": latest_file,
            "timestamp": datetime.fromtimestamp(os.path.getmtime(latest_file)).isoformat()
        }
    except Exception as e:
        print(f"Error getting latest file: {e}")
        return None

# Initialize latest_model after the helper is defined
found_file = get_latest_uploaded_file()
if found_file:
    latest_model = found_file
else:
    latest_model = {
        "path": "",
        "timestamp": datetime.now().isoformat()
    }

app = FastAPI()
app.mount("/animations", StaticFiles(directory="animations"), name="animations") 

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://simflection.myshopify.com",
        "http://localhost:8000",
        "http://localhost:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Recommended-Size", "X-Size-Comment"]
)

async def get_body_dim(file_path):
    """Run the processing script on the model file."""
    try:
        script_path = "scripts/get_body_dim/get_body_dim.js"  # Node.js script
        print(f"Running processing script on: {file_path}")
        
        process = await asyncio.create_subprocess_exec(
            'node', script_path, file_path,
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

async def sizing_rec():
    try:
        with open('scripts/get_body_dim/body_dim.json', 'r') as f:
            sizing_data = json.load(f)
    except Exception as e:
        print(f"Error reading sizing data: {e}")
        return {}
    size_guide_path = 'scripts/sizing_recommendation/size_guide.csv'
    gender = 'male'
    category = 'top'
    best_size, best_comment = get_size(size_guide_path, sizing_data, gender, category)
    print("sizing_rec output backend")
    print(best_size, best_comment)
    return best_size, best_comment

@app.get("/latest-model-info")
async def get_latest_model_info():
    global latest_model
    current_latest = get_latest_uploaded_file()
    if current_latest and current_latest["path"] != latest_model["path"]:
        latest_model = current_latest
    return latest_model

@app.get("/get-sizing")
async def get_sizing():
    global latest_model
    current_latest = get_latest_uploaded_file()
    print("in get_sizing", current_latest)
    
    if current_latest and os.path.exists(current_latest["path"]):
        try:
            # Update latest_model if there's a new file
            if current_latest["path"] != latest_model["path"]:
                latest_model = current_latest
            
            # Run the processing script
            print("before calling run_processing_script")
            await get_body_dim(current_latest["path"])
            recommended_size, recommended_comment = await sizing_rec()
            print("before unpack", recommended_size, recommended_comment)

            # Determine media type
            file_ext = os.path.splitext(current_latest["path"])[1].lower()
            media_type = {
                '.glb': 'model/gltf-binary',
                '.gltf': 'model/gltf+json',
                '.obj': 'model/obj',
                '.fbx': 'application/octet-stream'
            }.get(file_ext, 'application/octet-stream')
            
            headers = {
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Last-Modified": current_latest["timestamp"],
                "X-Recommended-Size": str(recommended_size),
                "X-Size-Comment": str(recommended_comment),
                "Access-Control-Allow-Origin": "https://simflection.myshopify.com",
                "Access-Control-Expose-Headers": "X-Recommended-Size, X-Size-Comment"
            }

            return FileResponse(
                current_latest["path"],
                media_type=media_type,
                filename=os.path.basename(current_latest["path"]),
                headers=headers
            )
        except Exception as e:
            print(f"Error in static-model endpoint: {str(e)}")
            return {"error": str(e)}, 500
            
    return {"error": "No model file found"}, 404

@app.post("/upload")
# async def upload_file(file: UploadFile = File(None), email: str="temp", useDefault: bool = False):
async def upload_file(
    file: UploadFile = File(None),     # 'file' from <input type="file">
    email: str = Form(None),          # 'email' from <input type="text" or "email">
    useDefault: bool = Form(False)    # 'useDefault' from a hidden/input form field
):
    global latest_model

    print("inside /upload")
    print(email)

    if useDefault:
        default_file = "default_joseph.fbx"
        default_file_path = os.path.join(UPLOAD_DIR, default_file)
        avatar_file_path = os.path.join(UPLOAD_DIR, "avatar.fbx")
        
        # Copy default file to avatar.fbx
        with open(default_file_path, "rb") as src, open(avatar_file_path, "wb") as dst:
            dst.write(src.read())
        
        latest_model = {
            "path": avatar_file_path,
            "timestamp": datetime.now().isoformat()
        }
        return {
            "filename": f"{UPLOAD_DIR}/default_joseph.fbx"
        }
    
    if file is None:
        return {"error": "File must be provided if useDefault is False"}, 400
    
    try:
        file_path = os.path.join(UPLOAD_DIR, "avatar.fbx")
        if os.path.exists(file_path):
            os.remove(file_path)
        
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
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


@app.post("/selected-animation")
async def selected_animation(request: Request):
    """
    Endpoint to receive the selected animation from the frontend
    and return the corresponding video URL.
    """

    body = await request.json()
    selected_animation = body.get("animation", "default")
    
    print(f"[Backend] Animation received: {selected_animation}")

    # TODO get animation from aws

    # Build the video URL
    video_url = f"http://localhost:8000/animations/{selected_animation}.mp4"

    # Return a JSON response with the video URL
    return {
        "message": "Animation received successfully",
        "video_url": video_url
    }

@app.get("/")
async def root():
    return {"message": "Backend is running"}

if __name__ == "__main__":
    print("Starting server at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
