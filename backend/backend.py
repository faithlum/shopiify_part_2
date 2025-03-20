import os
import json
import uvicorn
import asyncio
from datetime import datetime
import subprocess
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from scripts.sizing_recommendation.sizing_recommender import get_size
import boto3
import hashlib
import trimesh
import numpy as np

dynamodb = boto3.resource('dynamodb', region_name='us-east-2')
table = dynamodb.Table('user_data')
EMAIL = None

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

        global EMAIL
        if EMAIL == None:
            user_id = "default"
        else:
            user_id = generate_user_id(EMAIL)

        directory = os.path.dirname(file_path)
        os.makedirs(directory, exist_ok=True)

        print(f"Running processing script on: {file_path}")
        print(user_id)
        
        process = await asyncio.create_subprocess_exec(
            'node', script_path, file_path, user_id, 
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
    global EMAIL

    if EMAIL == None:
        user_id = "default"
    else:
        user_id = generate_user_id(EMAIL)

    try:
        with open(f'animations/{user_id}/body_dim.json', 'r') as f:
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
    global EMAIL

    if EMAIL == None:
        file_path = "animations/default/body_dim.json"
    else:
        user_id = generate_user_id(EMAIL)
        file_path = f"animations/{user_id}/body_dim.json"

    print(f"in get_sizing: {file_path}")
                
    
    if file_path and os.path.exists(file_path):
        try:
            # Run the processing script
            print("before calling run_processing_script")
            await get_body_dim(file_path)
            recommended_size, recommended_comment = await sizing_rec()
            print("before unpack", recommended_size, recommended_comment)

            # Determine media type
            file_ext = os.path.splitext(file_path)[1].lower()
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
                "X-Recommended-Size": str(recommended_size),
                "X-Size-Comment": str(recommended_comment),
                "Access-Control-Allow-Origin": "https://simflection.myshopify.com",
                "Access-Control-Expose-Headers": "X-Recommended-Size, X-Size-Comment"
            }

            return FileResponse(
                file_path,
                media_type=media_type,
                filename=os.path.basename(file_path),
                headers=headers
            )
        except Exception as e:
            print(f"Error in static-model endpoint: {str(e)}")
            return {"error": str(e)}, 500
            
    return {"error": "No model file found"}, 404

@app.get("/get-body-dim-and-model")
async def get_body_dim_and_model():
    print("in get_dim_and_model")
    current_latest = get_latest_uploaded_file()

    print(f"in body dim and model: {current_latest}")
    await get_body_dim(current_latest["path"])

    global EMAIL

    if EMAIL == None:
        user_id = "default"
    else:
        user_id = generate_user_id(EMAIL)
    try: 
        with open(f'animations/{user_id}/body_dim.json', 'r') as f:
            body_dim = json.load(f)
    except Exception as e:
        print(f"❌ Error getting body dim: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

    current_latest = get_latest_uploaded_file()

    print(current_latest)

    fbx_path = current_latest["path"]

    try:
        if EMAIL == None:
            glb_path = "animations/default/body_dim.glb"
        else:
            user_id = generate_user_id(EMAIL)
            glb_path = f"animations/{user_id}/body_dim.glb"

        if not os.path.exists(glb_path):
            cmd = [
                "assimp", "export",
                fbx_path, glb_path
            ]

            print("in get body dim and model")
            print(body_dim)
            print(cmd)

            try: 
                subprocess.run(cmd, check=True)
                glb = trimesh.load(glb_path)
                scene = trimesh.Scene(glb)
                color = (np.array([77, 77, 77, 255])).astype(np.uint8)  # Convert to 0-255 RGB

                # ✅ Apply colors to the objects separately
                for i, (name, mesh) in enumerate(glb.geometry.items()):
                    if isinstance(mesh, trimesh.Trimesh):
                        # Apply color to all vertices
                        mesh.visual.vertex_colors = np.tile(color, (mesh.vertices.shape[0], 1))
                        
                        # Add modified mesh back to scene
                        scene.add_geometry(mesh, node_name=f"modified_{name}")

                scene.export(glb_path)
                print(f"✅ Successfully converted {fbx_path} to {glb_path}")
            except subprocess.CalledProcessError as e:
                print(f"❌ Conversion failed: {e}")
                return JSONResponse(content={"error": f"Conversion failed: {str(e)}"}, status_code=500)


        output_url = f"https://api.simflection.tech/{glb_path}"

        return JSONResponse(content={
            "body_dim": body_dim,  # Ensure it's a dict
            "glb_url": output_url,
        }, status_code=200)

    except Exception as e:
        print(f"❌ Error in get body dim and model endpoint: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
    
def generate_user_id(email):
    return hashlib.sha256(email.encode()).hexdigest()[:16]

@app.post("/upload")
# async def upload_file(file: UploadFile = File(None), email: str="temp", useDefault: bool = False):
async def upload_file(
    file: UploadFile = File(None),     # 'file' from <input type="file">
    email: str = Form(None),          # 'email' from <input type="text" or "email">
    useDefault: bool = Form(False)    # 'useDefault' from a hidden/input form field
):
    global latest_model
    global EMAIL 

    EMAIL = email

    print(f"in upload endpoint: {useDefault}")
    print(f"email: {email}")

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
    
    print(f"file: {file}")
    
    if file is None:
        return {"error": "File must be provided if useDefault is False"}, 400
    
    try:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        print(f"file path: {file_path}")
        
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        latest_model = {
            "path": file_path,
            "timestamp": datetime.now().isoformat()
        }
        
        print(f"New model saved as: {file_path}")


        if EMAIL == None:
            user_id = "default"
        else:
            user_id = generate_user_id(EMAIL)

        get_body_dim(file_path)
        with open(f'animations/{user_id}/body_dim.json', 'r') as f:
            body_dim = json.load(f)

        print("CALL DB here")
        print(email)
        print(body_dim)

        user_id = generate_user_id(email)

        for k, v in body_dim.items():
            try:
                table.update_item(
                    Key={'user_id': user_id},
                    UpdateExpression=f"SET {k} = :{k}",
                    ExpressionAttributeValues={f':{k}': str(v)},
                    ConditionExpression="attribute_exists(user_id)"  # Ensures user_id exists
                )
                print("Row updated successfully!")

            except boto3.exceptions.botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    print("Error: user_id does not exist!")
                else:
                    print("Unexpected error:", e)

        return {
            "filename": file_path.split("/")[-1],
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

    global EMAIL
    
    body = await request.json()
    selected_animation = body.get("animation", "default")
    product_title = body.get("productTitle", "Unknown Title")
    product_id = body.get("productId", "Unknown ID")

    print(f"[Backend] Animation received: {selected_animation}")
    
    product_id_to_garment_name_mapping = {
        '9918248943925': "tank",
        '10032869409077': "longsleeve",
        '10032883958069': "pants_shorter",
        '9918239211829': "pants",
        '10032886087989': "shorts",
        '10032887365941': "shortsleeve",
        '10032890904885': "tight_dress",
        '10032900079925': "tshirt_unzipped"

    }

    garment_name = product_id_to_garment_name_mapping[product_id]

    if EMAIL == None:
        if selected_animation == "apose":
            output_url = f"https://api.simflection.tech/animations/default/{garment_name}/{selected_animation}.glb"
        else:
            output_url = f"https://api.simflection.tech/animations/default/{garment_name}/{selected_animation}.mp4"

        return {
            "message": "Animation received successfully",
            "output_url": output_url
        }


    user_id = generate_user_id(EMAIL)

    print(EMAIL)

    try:
        response = table.get_item(
            Key={'user_id': user_id}
        )
        print(response)
        height = response['Item']['height']
        bust = response['Item']['bust']
        waist = response['Item']['waist']
        hips = response['Item']['hips']
        inseam = response['Item']['inseam']
        gender = response['Item']['sex']
    except Exception as e:
        print("Error getting item:", e)

    print(height)

    if selected_animation == "apose":
        out_file = f"animations/{user_id}/{garment_name}/{selected_animation}.glb"
    else:
        out_file = f"animations/{user_id}/{garment_name}/{selected_animation}.mp4"

    print(f"out_file: {out_file}")

    if not os.path.exists(out_file):
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        cmd = [
            "conda", "run", "-n", "hood", 
            "python", "../../HOOD/get_simulation.py",
            "--height", height,
            "--bust", bust,
            "--waist", waist,
            "--hips", hips,
            "--inseam", inseam,
            "--pose", selected_animation,
            "--garment_name", garment_name,
            "--gender", gender.upper(),
            "--out_file", out_file,
            "--body_dim_to_smpl_model_dir", "../../HOOD/body_dim_to_smpl"
        ]

        print(cmd)

        process = subprocess.run(cmd, capture_output=True, text=True)

        if process.returncode != 0:
            # Log or handle error
            error_msg = process.stderr or "Unknown error"
            return {"error": f"Subprocess failed: {error_msg}"}
        
        output = process.stdout.strip()
        print("Subprocess output:", output)

    # Build the video URL
    output_url = f"http://api.simflection.tech/{out_file}"

    # Return a JSON response with the video URL
    return {
        "message": "Animation received successfully",
        "output_url": output_url
    }

@app.get("/")
async def root():
    return {"message": "Backend is running"}

if __name__ == "__main__":
    print("Starting server at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
