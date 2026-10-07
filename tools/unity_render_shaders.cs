// Body for the Unity MCP "execute code" call: renders a lit sphere and a cube with every shader
// under a folder and saves one PNG per shader, twice: with the default material plus a test
// texture ("default"), and with every keyword enabled, every *Enable* property set and the test
// texture in every 2D texture slot ("all"). Run it in an editor that compiles with fxc2 and in
// the stock one, then compare the two sets (tools/compare_images.py). Nothing is added to the
// scene: the objects are hidden and destroyed. Set the first three strings before use; the
// work runs after the call returns and ends by writing <root>/done.txt.
string tag = "fxc2";
string folder = "Assets/__fxc2_poiyomi";
string rootBase = "C:/Users/micha/Documents/FXC2/out/poi_render2_";
UnityEditor.EditorApplication.delayCall += () => {
string root = rootBase + tag;
var sb = new System.Text.StringBuilder();
var pattern = new UnityEngine.Texture2D(64, 64, UnityEngine.TextureFormat.RGBA32, true) { hideFlags = UnityEngine.HideFlags.HideAndDontSave };
for (int y = 0; y < 64; y++) for (int x = 0; x < 64; x++) {
  bool c = ((x / 8) + (y / 8)) % 2 == 0;
  pattern.SetPixel(x, y, new UnityEngine.Color(x / 63f, y / 63f, c ? 0.9f : 0.25f, c ? 1f : 0.6f));
}
pattern.Apply();
var camGo = new UnityEngine.GameObject("__fxc2_cam") { hideFlags = UnityEngine.HideFlags.HideAndDontSave };
var cam = camGo.AddComponent<UnityEngine.Camera>();
cam.enabled = false; cam.clearFlags = UnityEngine.CameraClearFlags.SolidColor; cam.backgroundColor = new UnityEngine.Color(0.2f, 0.3f, 0.4f, 1f);
cam.cullingMask = 1 << 31; cam.fieldOfView = 30f; cam.nearClipPlane = 0.1f; cam.farClipPlane = 50f; cam.allowHDR = false; cam.allowMSAA = false;
camGo.transform.position = new UnityEngine.Vector3(1000f, 1000f, 996f); camGo.transform.LookAt(new UnityEngine.Vector3(1000f, 1000f, 1000f));
var lightGo = new UnityEngine.GameObject("__fxc2_light") { hideFlags = UnityEngine.HideFlags.HideAndDontSave };
var light = lightGo.AddComponent<UnityEngine.Light>(); light.type = UnityEngine.LightType.Directional; light.intensity = 0.7f; light.color = new UnityEngine.Color(1f, 0.9f, 0.75f); light.cullingMask = 1 << 31;
lightGo.transform.rotation = UnityEngine.Quaternion.Euler(40f, 30f, 0f);
var sphere = UnityEngine.GameObject.CreatePrimitive(UnityEngine.PrimitiveType.Sphere); sphere.hideFlags = UnityEngine.HideFlags.HideAndDontSave; sphere.layer = 31;
sphere.transform.position = new UnityEngine.Vector3(999.45f, 1000f, 1000f);
var cube = UnityEngine.GameObject.CreatePrimitive(UnityEngine.PrimitiveType.Cube); cube.hideFlags = UnityEngine.HideFlags.HideAndDontSave; cube.layer = 31;
cube.transform.position = new UnityEngine.Vector3(1000.6f, 1000f, 1000f); cube.transform.rotation = UnityEngine.Quaternion.Euler(20f, 35f, 10f); cube.transform.localScale = UnityEngine.Vector3.one * 0.7f;
var rt = new UnityEngine.RenderTexture(512, 512, 24, UnityEngine.RenderTextureFormat.ARGB32);
var tex = new UnityEngine.Texture2D(512, 512, UnityEngine.TextureFormat.RGBA32, false);
var sw = System.Diagnostics.Stopwatch.StartNew();
for (int mode = 0; mode < 2; mode++) {
 string outDir = root + (mode == 0 ? "/default" : "/all");
 System.IO.Directory.CreateDirectory(outDir);
 foreach (var g in UnityEditor.AssetDatabase.FindAssets("t:Shader", new[] { folder })) {
  var path = UnityEditor.AssetDatabase.GUIDToAssetPath(g);
  var sh = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Shader>(path);
  if (sh == null) continue;
  var mat = new UnityEngine.Material(sh) { hideFlags = UnityEngine.HideFlags.HideAndDontSave };
  int kw = 0, fl = 0, tx = 0;
  if (mat.HasProperty("_MainTex")) mat.SetTexture("_MainTex", pattern);
  if (mat.HasProperty("_Color")) mat.SetColor("_Color", new UnityEngine.Color(0.85f, 0.7f, 0.6f, 1f));
  if (mode == 1) {
   foreach (var k in sh.keywordSpace.keywords) { if (!k.isOverridable) continue; mat.EnableKeyword(k); kw++; }
   int pcnt = sh.GetPropertyCount();
   for (int i = 0; i < pcnt; i++) {
    var pn = sh.GetPropertyName(i); var pt = sh.GetPropertyType(i);
    if ((pt == UnityEngine.Rendering.ShaderPropertyType.Float || pt == UnityEngine.Rendering.ShaderPropertyType.Range) && (pn.Contains("Enable") || pn.EndsWith("Enabled") || pn.Contains("Toggle"))) { mat.SetFloat(pn, 1f); fl++; }
    if (pt == UnityEngine.Rendering.ShaderPropertyType.Texture && sh.GetPropertyTextureDimension(i) == UnityEngine.Rendering.TextureDimension.Tex2D) { mat.SetTexture(pn, pattern); tx++; }
   }
  }
  sphere.GetComponent<UnityEngine.Renderer>().sharedMaterial = mat; cube.GetComponent<UnityEngine.Renderer>().sharedMaterial = mat;
  cam.targetTexture = rt; cam.Render(); cam.Render();
  UnityEngine.RenderTexture.active = rt; tex.ReadPixels(new UnityEngine.Rect(0, 0, 512, 512), 0, 0); tex.Apply(); UnityEngine.RenderTexture.active = null;
  var name = System.IO.Path.GetFileNameWithoutExtension(path).Replace(' ', '_');
  System.IO.File.WriteAllBytes(outDir + "/" + name + ".png", UnityEngine.ImageConversion.EncodeToPNG(tex));
  int errs = 0; foreach (var m in UnityEditor.ShaderUtil.GetShaderMessages(sh)) if (m.severity == UnityEditor.Rendering.ShaderCompilerMessageSeverity.Error) errs++;
  sb.AppendLine((mode == 0 ? "default " : "all ") + name + " keywords=" + kw + " floats=" + fl + " textures=" + tx + " errors=" + errs + " ms=" + sw.ElapsedMilliseconds);
  System.IO.File.WriteAllText(root + "/progress.txt", sb.ToString());
  cam.targetTexture = null; UnityEngine.Object.DestroyImmediate(mat);
 }
}
rt.Release(); UnityEngine.Object.DestroyImmediate(rt); UnityEngine.Object.DestroyImmediate(tex); UnityEngine.Object.DestroyImmediate(pattern);
UnityEngine.Object.DestroyImmediate(sphere); UnityEngine.Object.DestroyImmediate(cube); UnityEngine.Object.DestroyImmediate(lightGo); UnityEngine.Object.DestroyImmediate(camGo);
System.IO.File.WriteAllText(root + "/done.txt", sb.ToString());
};
return "scheduled";
