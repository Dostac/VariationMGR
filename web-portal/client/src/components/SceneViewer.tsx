import { Suspense } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Environment, useGLTF } from "@react-three/drei";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";

interface Props {
  glbUrl: string;
}

function Model({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  return <primitive object={scene} />;
}

export default function SceneViewer({ glbUrl }: Props) {
  return (
    <Box
      sx={{
        width: "100%",
        height: "100%",
        minHeight: 400,
        borderRadius: 2,
        overflow: "hidden",
        bgcolor: "background.paper",
      }}
    >
      <Suspense
        fallback={
          <Box
            display="flex"
            justifyContent="center"
            alignItems="center"
            height="100%"
          >
            <CircularProgress />
          </Box>
        }
      >
        <Canvas
          camera={{ position: [5, 3, 5], fov: 50 }}
          style={{ width: "100%", height: "100%" }}
        >
          <ambientLight intensity={0.4} />
          <directionalLight position={[5, 10, 5]} intensity={1} />
          <Model url={glbUrl} />
          <OrbitControls
            makeDefault
            enableDamping
            dampingFactor={0.1}
            minDistance={1}
            maxDistance={50}
          />
          <Environment preset="apartment" background={false} />
        </Canvas>
      </Suspense>
    </Box>
  );
}
