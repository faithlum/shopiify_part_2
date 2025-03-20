import * as THREE from 'three';
import { FBXLoader } from 'three/examples/jsm/loaders/FBXLoader.js';
import * as SkeletonUtils from 'three/examples/jsm/utils/SkeletonUtils.js';
import { MeshBVH } from 'three-mesh-bvh';
import path from 'path';
import { fileURLToPath } from 'url';

import fs from 'fs/promises';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
global.window = {};

// === Global variables for slicing ===
let colliderBvh, colliderMesh, outlineLines;

// Global temporary variables for slicing.
const tempVector  = new THREE.Vector3();
const tempVector1 = new THREE.Vector3();
const tempVector2 = new THREE.Vector3();
const tempVector3 = new THREE.Vector3();
const tempLine    = new THREE.Line3();

// Scene setup
const scene = new THREE.Scene();
const fbxLoader = new FBXLoader();

// Get file paths
const avatarInFilePath = process.argv[2];
const user_id = process.argv[3];
const avatarFilePath = path.resolve(__dirname, `../../${avatarInFilePath}`);
const tposeFilePath = path.resolve(__dirname, `../../uploads/tpose.fbx`);
const bodyDimFilePath = path.resolve(__dirname, `../../animations/${user_id}/body_dim.json`);

console.log("bodyDimFilePath:");
console.log(bodyDimFilePath);

// Animation variables
let avatar, tpose;


// **Load FBX file as a buffer and parse it**
async function loadFBXModel(filePath) {
  try {
      console.log(`🔹 Loading FBX: ${filePath}`);
      const data = await fs.readFile(filePath);
      return fbxLoader.parse(data.buffer, '');
  } catch (error) {
      console.error(`❌ Error loading FBX ${filePath}:`, error);
      return null;
  }
}

// **Main function to load models in order**
async function run_script() {
  // **Step 1: Load the Avatar Model**
  avatar = await loadFBXModel(avatarFilePath);
  if (!avatar) return;

  console.log("✅ Avatar Loaded!");
  avatar.visible = true;
  avatar.position.set(0, 0, 0);
  scene.add(avatar);

  // **Step 2: Load the T-Pose Model**
  tpose = await loadFBXModel(tposeFilePath);
  if (!tpose) return;

  console.log("✅ T-Pose Loaded!");
  tpose.visible = false;

  // **Step 3: Apply the T-Pose to the Avatar**
  applyPose(avatar, tpose);

  // **Step 4: Measure the Avatar**
  measureAvatar(avatar);
}

function applyPose(avatar, tpose) {
  if (!avatar || !tpose) {
    console.error("Both avatar and T-pose skeleton must be loaded.");
    return;
  }
  avatar.traverse((child) => {
    if (child.isBone) {
      const tposeBone = tpose.getObjectByName(child.name);
      if (tposeBone) {
        child.quaternion.copy(tposeBone.quaternion);
      }
    }
  });
  avatar.updateMatrixWorld(true);
  avatar.position.set(0, 0, 0);

  // Clone the avatar with applied transformations
  const clonedAvatar = SkeletonUtils.clone(avatar);

  // Create a group to hold baked (static) meshes
  const bakedGroup = new THREE.Group();

  // Traverse the cloned avatar and bake skinned meshes
  clonedAvatar.traverse((child) => {
      if (child instanceof THREE.SkinnedMesh) {
          const geometry = child.geometry.clone();
          const nonIndexedGeometry = geometry.toNonIndexed();
          const positionAttribute = nonIndexedGeometry.getAttribute('position');

          const bakedPositions = new Float32Array(positionAttribute.count * 3);
          const vertex = new THREE.Vector3();

          for (let i = 0; i < positionAttribute.count; i++) {
              vertex.fromBufferAttribute(positionAttribute, i);
              child.applyBoneTransform(i, vertex);
              bakedPositions[i * 3] = vertex.x;
              bakedPositions[i * 3 + 1] = vertex.y;
              bakedPositions[i * 3 + 2] = vertex.z;
          }

          nonIndexedGeometry.setAttribute('position', new THREE.BufferAttribute(bakedPositions, 3));
          nonIndexedGeometry.computeVertexNormals();

          const staticMesh = new THREE.Mesh(nonIndexedGeometry, child.material);
          staticMesh.position.copy(child.position);
          staticMesh.rotation.copy(child.rotation);
          staticMesh.scale.copy(child.scale);

          bakedGroup.add(staticMesh);
      } else if (child instanceof THREE.Mesh) {
          bakedGroup.add(child.clone());
      }
  });

  setupColliderAndOutline(bakedGroup);
}

function setupColliderAndOutline(avatar) {
  avatar.traverse(child => {
    if (child.isMesh && !colliderMesh) {
      colliderMesh = child.clone();
      colliderMesh.visible = true;
      colliderMesh.geometry.applyMatrix4(colliderMesh.matrixWorld);
      colliderMesh.matrix.identity();
      colliderMesh.matrixWorld.identity();
      colliderMesh.updateMatrixWorld(true);
      colliderBvh = new MeshBVH(colliderMesh.geometry, { maxLeafTris: 3 });
      colliderMesh.geometry.boundsTree = colliderBvh;
    }
  });
  const lineCount = 300000; // adjust as needed
  const lineGeometry = new THREE.BufferGeometry();
  const linePosAttr = new THREE.BufferAttribute(new Float32Array(lineCount), 3, false);
  linePosAttr.setUsage(THREE.DynamicDrawUsage);
  lineGeometry.setAttribute('position', linePosAttr);
  outlineLines = new THREE.LineSegments(
    lineGeometry
  );
  outlineLines.frustumCulled = false;
}

function measureCircumference(desiredHeight) { 
  const clippingPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -desiredHeight);

  let index = 0;
  const posAttr = outlineLines.geometry.attributes.position;
  let intersectionPoints = [];

  colliderBvh.shapecast({
    intersectsBounds: box => clippingPlane.intersectsBox(box),
    intersectsTriangle: (tri) => {
      let count = 0;

      tempLine.start.copy(tri.a);
      tempLine.end.copy(tri.b);
      if (clippingPlane.intersectLine(tempLine, tempVector)) {
        posAttr.setXYZ(index, tempVector.x, tempVector.y, tempVector.z);
        intersectionPoints.push(tempVector.clone());
        index++; count++;
      }

      tempLine.start.copy(tri.b);
      tempLine.end.copy(tri.c);
      if (clippingPlane.intersectLine(tempLine, tempVector)) {
        posAttr.setXYZ(index, tempVector.x, tempVector.y, tempVector.z);
        intersectionPoints.push(tempVector.clone());
        index++; count++;
      }

      tempLine.start.copy(tri.c);
      tempLine.end.copy(tri.a);
      if (clippingPlane.intersectLine(tempLine, tempVector)) {
        posAttr.setXYZ(index, tempVector.x, tempVector.y, tempVector.z);
        intersectionPoints.push(tempVector.clone());
        index++; count++;
      }

      if (count === 3) {
        tempVector1.fromBufferAttribute(posAttr, index - 3);
        tempVector2.fromBufferAttribute(posAttr, index - 2);
        tempVector3.fromBufferAttribute(posAttr, index - 1);
        if (tempVector3.equals(tempVector1) || tempVector3.equals(tempVector2)) {
          count--; index--;
        } else if (tempVector1.equals(tempVector2)) {
          posAttr.setXYZ(index - 2, tempVector3.x, tempVector3.y, tempVector3.z);
          count--; index--;
        }
      }

      if (count !== 2) {
        index -= count;
      }
    }
  });

  outlineLines.geometry.setDrawRange(0, index);
  posAttr.needsUpdate = true;

  let sortedPoints = [];
  let usedIndices = new Set();

  let currentIndex = 0;
  sortedPoints.push(intersectionPoints[currentIndex]);
  usedIndices.add(currentIndex);

  while (sortedPoints.length < intersectionPoints.length) {
    let nearestIndex = -1;
    let minDist = Infinity;
    let currentPoint = sortedPoints[sortedPoints.length - 1];

    for (let i = 0; i < intersectionPoints.length; i++) {
      if (usedIndices.has(i)) continue;
      let dist = currentPoint.distanceTo(intersectionPoints[i]);
      if (dist < minDist) {
        minDist = dist;
        nearestIndex = i;
      }
    }

    if (nearestIndex !== -1) {
      sortedPoints.push(intersectionPoints[nearestIndex]);
      usedIndices.add(nearestIndex);
    }
  }

  sortedPoints.push(sortedPoints[0]);

  let totalLength = 0;
  for (let i = 0; i < sortedPoints.length - 1; i++) {
    totalLength += sortedPoints[i].distanceTo(sortedPoints[i + 1]);
  }

  return totalLength;
}

function measureAvatar(avatar) {
  let height, bust, waist, hips, shoulderWidth, sleeveLength, inseam;
  let mixamorigSpine2, mixamorigSpine1, mixamorigSpine, mixamorigHips, mixamorigRightUpLeg;
  let mixamorigLeftArm, mixamorigRightArm, mixamorigRightHand, mixamorigLeftHand, mixamorigRightFoot;

  avatar.traverse((child) => {
    if (child.isBone) {
      const jointName = child.name;
      const position = new THREE.Vector3();
      child.getWorldPosition(position);
      if (jointName == "mixamorigSpine2") {
        mixamorigSpine2 = [position.x, position.y, position.z];
      } else if (jointName == "mixamorigSpine1") {
        mixamorigSpine1 = [position.x, position.y, position.z];
      } else if (jointName == "mixamorigSpine") {
        mixamorigSpine = [position.x, position.y, position.z];
      } else if (jointName == "mixamorigHips") {
        mixamorigHips = [position.x, position.y, position.z];
      } else if (jointName == "mixamorigRightUpLeg") {
        mixamorigRightUpLeg = [position.x, position.y, position.z];
      } else if (jointName == "mixamorigLeftArm") {
        mixamorigLeftArm = [position.x, position.y, position.z];
      } else if (jointName == "mixamorigRightArm") {
        mixamorigRightArm = [position.x, position.y, position.z];
      } else if (jointName == "mixamorigRightHand") {
        mixamorigRightHand = [position.x, position.y, position.z];
      } else if (jointName == "mixamorigRightFoot") {
        mixamorigRightFoot = [position.x, position.y, position.z];
      } else if (jointName == "mixamorigLeftHand") {
        mixamorigLeftHand = [position.x, position.y, position.z];
      }
    }
  });

  const bbox = new THREE.Box3().setFromObject(avatar);
  height = bbox.max.y - bbox.min.y;

  const maxIter = 10;
  let maxCircumference = 0;
  let bestHeight;

  for (let i = 0; i <= (maxIter-1); i++) {
    let currentHeight = mixamorigSpine2[1] + ((mixamorigSpine1[1] - mixamorigSpine2[1]) * (i / (maxIter-1)));
    let circumference = measureCircumference(currentHeight);

    if (circumference > maxCircumference) {
      maxCircumference = circumference;
      bestHeight = currentHeight;
    }
  }
  bust = maxCircumference;

  waist = measureCircumference(mixamorigSpine[1]);

  let hipsHeight = (mixamorigHips[1] + mixamorigRightUpLeg[1]) / 2;
  hips = measureCircumference(hipsHeight);

  shoulderWidth = ((mixamorigLeftArm[0] - mixamorigRightArm[0])**2 + (mixamorigLeftArm[2] - mixamorigRightArm[2])**2 + (mixamorigLeftArm[1] - mixamorigRightArm[1])**2)**0.5;

  sleeveLength = ((mixamorigLeftArm[0] - mixamorigLeftHand[0])**2 + (mixamorigLeftArm[2] - mixamorigLeftHand[2])**2 + (mixamorigLeftArm[1] - mixamorigLeftHand[1])**2)**0.5;

  inseam = mixamorigHips[1] - mixamorigRightFoot[1];

  console.log("Model height:", height);
  console.log("Bust:", bust);
  console.log("Waist:", waist);
  console.log("Hips:", hips);
  console.log("Shoulder width:", shoulderWidth);
  console.log("Sleeve length:", sleeveLength);
  console.log("Inseam:", inseam);

  const bodyDimensions = {
    height: height,
    bust: bust,
    waist: waist,
    hips: hips,
    shoulderWidth: shoulderWidth,
    sleeveLength: sleeveLength,
    inseam: inseam
  };

  fs.writeFile(bodyDimFilePath, JSON.stringify(bodyDimensions, null, 2))
    .then(() => {
      console.log(`Body dimensions saved to ${bodyDimFilePath}`);
    })
    .catch((error) => {
      console.error(`Error saving body dimensions:`, error);
    });
}


run_script();