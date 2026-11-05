import sys
t=open('template.html').read()
d=open('data.json').read().replace('</','<\\/')
e=open('engine.js').read()+'\n'+open('rt.js').read()
t=t.replace('__DATA__',d,1).replace('/*__ENGINE__*/',e,1)
open('horaires-grand-reims.html','w').write(t)
print(len(t))
