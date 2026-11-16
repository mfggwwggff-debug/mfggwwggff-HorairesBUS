# Recompresse les images d'un .glb « Pôle Studio · compact GLB » (meshopt) sans toucher aux maillages.
import json,struct,sys,io,hashlib
from PIL import Image
src,dst=sys.argv[1],sys.argv[2]
b=open(src,'rb').read()
jl=struct.unpack('<I',b[12:16])[0];J=json.loads(b[20:20+jl]);o=20+jl
bl,bt=struct.unpack('<II',b[o:o+8]);BIN=b[o+8:o+8+bl]
BV=J['bufferViews']
imgv={im['bufferView']:i for i,im in enumerate(J.get('images',[]))}
# plages utilisées dans le buffer 0 : vues simples et données compressées meshopt
ranges=[]
for i,v in enumerate(BV):
    ext=v.get('extensions',{}).get('EXT_meshopt_compression')
    if ext and ext.get('buffer',0)==0: ranges.append((ext.get('byteOffset',0),ext['byteLength'],i,'ext'))
    elif v.get('buffer',0)==0: ranges.append((v.get('byteOffset',0),v['byteLength'],i,'plain'))
cache={};out=bytearray();before=after=0
for off,ln,i,kind in sorted(ranges):
    data=BIN[off:off+ln]
    if kind=='plain' and i in imgv:
        before+=ln;h=hashlib.md5(data).hexdigest()
        if h not in cache:
            p=Image.open(io.BytesIO(data));p.load()
            rgba=p.convert('RGBA');alpha=rgba.getextrema()[3][0]<250
            bio=io.BytesIO()
            if alpha:
                rgba.quantize(colors=192,method=Image.Quantize.FASTOCTREE).save(bio,'PNG',optimize=True);mime='image/png'
            else:
                rgba.convert('RGB').save(bio,'JPEG',quality=84,optimize=True);mime='image/jpeg'
            nd=bio.getvalue()
            if len(nd)>=len(data): nd,mime=data,J['images'][imgv[i]].get('mimeType','image/png')
            cache[h]=(nd,mime)
        data,mime=cache[h];J['images'][imgv[i]]['mimeType']=mime;after+=len(data)
    while len(out)%4: out.append(0)
    no=len(out);out.extend(data)
    if kind=='ext': BV[i]['extensions']['EXT_meshopt_compression']['byteOffset']=no
    else: BV[i]['byteOffset']=no;BV[i]['byteLength']=len(data)
while len(out)%4: out.append(0)
J['buffers'][0]['byteLength']=len(out)
js=json.dumps(J,separators=(',',':')).encode();js+=b' '*((4-len(js)%4)%4)
glb=struct.pack('<III',0x46546C67,2,12+8+len(js)+8+len(out))+struct.pack('<II',len(js),0x4E4F534A)+js+struct.pack('<II',len(out),0x004E4942)+bytes(out)
open(dst,'wb').write(glb)
print(f"{len(b)/1e6:.1f} Mo -> {len(glb)/1e6:.1f} Mo (images {before/1e6:.1f} -> {after/1e6:.1f} Mo)")
