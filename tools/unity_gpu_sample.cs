// Body for the Unity MCP `unity_execute_code` tool (not a standalone script).
// Samples the GPU frame time of play mode once a second for 30 seconds,
// starting when the game clock reaches 30 s so that runs are comparable, and
// writes the samples to the file named in `path`; the last line is "done".
var path = "C:/Users/micha/Documents/FXC2/out/unity_gpu_samples.txt";
System.IO.File.WriteAllText(path, "");
int count = 0;
UnityEditor.EditorApplication.CallbackFunction cb = null;
double next = 0;
cb = () => {
  if (!UnityEngine.Application.isPlaying || UnityEngine.Time.time < 30f) return;
  if (UnityEditor.EditorApplication.timeSinceStartup < next) return;
  next = UnityEditor.EditorApplication.timeSinceStartup + 1.0;
  UnityEngine.FrameTimingManager.CaptureFrameTimings();
  var t = new UnityEngine.FrameTiming[120];
  uint n = UnityEngine.FrameTimingManager.GetLatestTimings(120, t);
  double gpu = 0, cpu = 0; for (int i = 0; i < n; i++) { gpu += t[i].gpuFrameTime; cpu += t[i].cpuFrameTime; }
  System.IO.File.AppendAllText(path, "t=" + UnityEngine.Time.time.ToString("F1") + " n=" + n + " gpu_ms=" + (gpu / System.Math.Max(1, n)).ToString("F4") + " cpu_ms=" + (cpu / System.Math.Max(1, n)).ToString("F4") + " frame=" + UnityEngine.Time.frameCount + "\n");
  if (++count >= 30) { UnityEditor.EditorApplication.update -= cb; System.IO.File.AppendAllText(path, "done\n"); }
};
UnityEditor.EditorApplication.update += cb;
return "armed";
