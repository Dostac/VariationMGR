/*
 * VirtualBuilders – Variation Manager & Batch Renderer macroscripts.
 *
 * Placed by the installer into each detected 3ds Max MacroScripts folder.
 * The installDir variable is patched by the Inno Setup [Code] section at
 * install time so it always points to the correct Program Files path.
 */

macroScript VB_VariationMGR
    category:"VirtualBuilders"
    buttonText:"Variation Manager"
    tooltip:"Open the VirtualBuilders Variation Manager"
(
    local installDir = @"C:\Program Files\VirtualBuilders\VariationMGR\plugin"
    python.Execute ("import sys; p = r'" + installDir + "'; sys.path.insert(0, p) if p not in sys.path else None")
    python.ExecuteFile (installDir + @"\main.py")
)

macroScript VB_BatchRenderer
    category:"VirtualBuilders"
    buttonText:"Batch Renderer"
    tooltip:"Open the VirtualBuilders Batch Renderer"
(
    local installDir = @"C:\Program Files\VirtualBuilders\VariationMGR\plugin"
    python.Execute ("import sys; p = r'" + installDir + "'; sys.path.insert(0, p) if p not in sys.path else None")
    python.Execute ("import main; main.launch_batch_renderer()")
)
