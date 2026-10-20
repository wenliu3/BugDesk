# BugDesk 标识资源

用户选择的方案：字母 B，来自 design/logo-concepts/2026-10-20/03-b-monogram.png。

正式母图由内置 image_gen 编辑生成，保留 B、斜向断口、文件夹形状与薄荷绿色点缀，圆角方块外透明。生成提示词如下：

Use case: precise-object-edit, logo-brand. Edit target: the supplied selected BugDesk B monogram app icon.
Prepare this exact selected design as a production-ready app logo. Preserve the distinctive white B silhouette, its diagonal break, the two folder-shaped counters, and mint inset in the lower counter. Preserve the rounded-square tile and relative proportions.
Make the tile completely flat uniform deep petrol teal (#064E61), the B pure white, and the mint accent flat (#4DE7BE). Remove all gradients and grain. Only the space OUTSIDE the rounded-square tile must be genuinely transparent. Every part INSIDE the tile including the B counters must be fully opaque and free of holes, spots, stains or transparency. Keep anti-aliased smooth edges, clear strong shapes. Center the tile with a small even transparent margin around it, square canvas 1024x1024. No added details, text, shadow, border, mockup, checkerboard or alternate version. One icon only.

文件：

- bugdesk-logo.png：高分辨率透明 PNG 母图。
- bugdesk.ico：供现有 Windows 打包配置使用的多尺寸图标（16、24、32、48、64、128、256）。
- ../web/bugdesk-logo.png：页面使用的 128px PNG。
- ../web/favicon.ico：与 Windows ICO 相同的浏览器标签图标。

在 Windows 的 PowerShell 中运行 tools/prepare_logo.ps1，可以从母图重新生成 PNG 和 ICO。此脚本只进行尺寸和封装格式转换，不重新生成图形，不增加运行时依赖。

从 1.2.0 开始，页面、浏览器标签和 Windows EXE 统一使用本标识。现有 build_windows.py 会在打包时嵌入 ICO，并收集 web 中的页面资源。
