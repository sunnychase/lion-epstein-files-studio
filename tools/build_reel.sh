#!/bin/bash
# build_reel.sh — cut the showcase reel from the scene recordings: title card, seven captioned scenes with 0.5 s cross-fades, end card,
# an original synthesised score; 16:9 master + phone, 9:16 phone, a 14 s preview .webp and a 10 s .gif for the README.
set -euo pipefail
cd "$(dirname "$0")"; F=/usr/share/fonts/truetype/noto; B=$F/NotoSans-Bold.ttf; K=$F/NotoSans-Black.ttf; R=$F/NotoSans-Regular.ttf
W=1920; H=1080; FPS=30; XF=0.5; mkdir -p seg
card(){ # name seconds line1 line2 line3
  ffmpeg -v error -y -f lavfi -i "color=c=0x0f1218:s=${W}x${H}:r=$FPS:d=$2" -vf "drawbox=x=0:y=$((H/2-150)):w=10:h=300:color=0xd9a441:t=fill,\
drawtext=fontfile=$K:text='$3':fontcolor=0xf2f3f6:fontsize=96:x=60:y=$((H/2-150)),\
drawtext=fontfile=$B:text='$4':fontcolor=0xd9a441:fontsize=54:x=62:y=$((H/2-30)),\
drawtext=fontfile=$R:text='$5':fontcolor=0x9aa3b2:fontsize=30:x=62:y=$((H/2+60)),\
drawtext=fontfile=$R:text='© 2026 Sunny Chase - Lion Studios.':fontcolor=0x6b7280:fontsize=24:x=62:y=$((H-70)),fade=t=in:st=0:d=0.6,fade=t=out:st=$(python3 -c "print($2-0.6)"):d=0.6" -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p seg/$1.mp4; }
scene(){ # name src start seconds caption
  local cap=${5//:/\\:}
  ffmpeg -v error -y -ss "$3" -t "$4" -i "$2" -vf "scale=${W}:${H}:flags=lanczos,fps=$FPS,\
drawbox=x=0:y=$((H-150)):w=$W:h=150:color=0x0f1218@0.86:t=fill,drawbox=x=60:y=$((H-128)):w=8:h=106:color=0xd9a441:t=fill,\
drawtext=fontfile=$B:text='$cap':fontcolor=0xf2f3f6:fontsize=44:x=88:y=$((H-122)),\
drawtext=fontfile=$R:text='The Epstein Files - Lion Studios':fontcolor=0xd9a441:fontsize=26:x=88:y=$((H-60)),\
drawtext=fontfile=$R:text='© Sunny Chase - Lion Studios':fontcolor=0xffffff@0.55:fontsize=22:x=w-tw-40:y=$((H-50))" -an -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p seg/$1.mp4; }
card 00-title 4 "THE EPSTEIN FILES" "Lion Studios" "A detective desk over the public court and government records. Every link backed by a quoted page."
scene 01 01-dashboard.webm 4 10 "A dashboard over half a million pages: patterns, leads, strongest connections"
scene 02 02-timeline.webm 5.5 6 "The whole record by year, down to the pages behind any bar"
scene 03 03-bubbles.webm 6 9 "3D bubbles: who shares pages with whom, routes pinpointed in gold"
scene 04 04-globe.webm 9 11 "A real Earth: places, flight legs and photo pages on the globe"
scene 05 05-money.webm 4 7 "Follow the money: who paid whom, flagged amounts, banks, jurisdictions"
scene 06 06-graph.webm 4 6 "Every connection carries its evidence pages. Redacted parties stay redacted"
scene 07 07-leads.webm 3.5 5 "Leads, public figures, redaction hot spots and a case notebook"
card 99-end 5 "THE EPSTEIN FILES" "github.com/sunnychase/lion-epstein-files-studio" "Built by Sunny Chase with Claude (Anthropic). Public records only. Nothing here is a finding."
# cross-fades
segs=(00-title 01 02 03 04 05 06 07 99-end); inputs=(); durs=()
for s in "${segs[@]}"; do inputs+=(-i seg/$s.mp4); durs+=($(ffprobe -v error -show_entries format=duration -of csv=p=0 seg/$s.mp4)); done
fc=""; off=0; prev="[0:v]"
for i in $(seq 1 $((${#segs[@]}-1))); do off=$(python3 -c "print(round($off + ${durs[$((i-1))]} - $XF, 3))"); out="[v$i]"; [ $i -eq $((${#segs[@]}-1)) ] && out="[vout]"; fc+="${prev}[$i:v]xfade=transition=fade:duration=$XF:offset=$off$out;"; prev="$out"; done
total=$(python3 -c "print(round($off + ${durs[-1]}, 3))"); echo "video length $total s"
ffmpeg -v error -y "${inputs[@]}" -i score.wav -filter_complex "${fc%;};[${#segs[@]}:a]atrim=0:$total,afade=t=in:st=0:d=1,afade=t=out:st=$(python3 -c "print($total-3)"):d=3[aout]" -map "[vout]" -map "[aout]" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart the-epstein-files-reel-16x9-master.mp4
ffmpeg -v error -y -i the-epstein-files-reel-16x9-master.mp4 -c:v libx264 -preset slow -crf 26 -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart the-epstein-files-reel-16x9-phone.mp4
# 9:16 for phones: the 16:9 picture centred on a blurred, enlarged copy of itself
ffmpeg -v error -y -i the-epstein-files-reel-16x9-master.mp4 -filter_complex "[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5,eq=brightness=-0.25[bg];[b]scale=1080:608[fg];[bg][fg]overlay=0:656" -c:v libx264 -preset slow -crf 24 -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart the-epstein-files-reel-9x16-phone.mp4
# README preview: 14 s (bubbles + globe) as animated webp, and a 10 s gif
st=$(python3 -c "print(round(${durs[0]}+${durs[1]}+${durs[2]} - 3*$XF, 2))")
ffmpeg -v error -y -ss $st -t 14 -i the-epstein-files-reel-16x9-master.mp4 -vf "fps=12,scale=960:-1:flags=lanczos" -loop 0 -q:v 70 -compression_level 6 preview.webp
ffmpeg -v error -y -ss $st -t 10 -i the-epstein-files-reel-16x9-master.mp4 -vf "fps=10,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=160[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4" -loop 0 preview.gif
ffmpeg -v error -y -ss 1 -i the-epstein-files-reel-16x9-master.mp4 -frames:v 1 -vf "scale=1280:-1" the-epstein-files-reel-16x9-master.jpg
ls -la the-epstein-files-reel-*.mp4 preview.webp preview.gif | awk '{print $5, $NF}'
