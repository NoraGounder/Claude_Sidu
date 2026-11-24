/* quailworks.co — hero object renderer (WebGL)
 * Written by Qwen 4 Max through OpenRouter on 2026-11-24 from a design brief, chosen over three other models,
 * reviewed and integrated by Claude. When WebGL is unavailable, hero.js draws the line version instead.
 * Dependency-free WebGL1 raymarcher (SDF). One file, one IIFE, CSP-safe.
 * Shapes: data-shape="knot" (2,3 torus knot) | "coil" (7-turn spring + damper).
 * Falls back to nothing (CSS background remains) when WebGL is unavailable.
 */
(function () {
  'use strict';

  /* ---------------------------------------------------------------- config */
  var DPR_CAP      = 1.5;      // raymarching is fill-rate bound
  var MAX_PIXELS   = 1150000;  // internal pixel budget before quality factor
  var Q_MIN        = 0.50;
  var Q_MAX        = 1.00;
  var Q_START      = 0.85;
  var BREAKPOINT   = 860;      // px, layout switch
  var STATIC_TIME  = { knot: 2.4, coil: 1.1 };

  /* --------------------------------------------------------------- shaders */
  var VERT = 'attribute vec2 aPos;void main(){gl_Position=vec4(aPos,0.0,1.0);}';

  var FRAG_BODY = [
    '#ifdef GL_FRAGMENT_PRECISION_HIGH',
    'precision highp float;',
    '#else',
    'precision mediump float;',
    '#endif',
    'uniform vec2  uRes;',
    'uniform vec2  uCenter;',   // object centre, GL space (y up)
    'uniform vec2  uPointer;',  // -1..1 parallax
    'uniform float uTime;',
    'uniform mat3  uObj;',      // world -> object rotation

    'const float PI  = 3.14159265;',
    'const float TAU = 6.28318531;',
    'const vec3  ACC = vec3(1.0,0.1022,0.0056);', // #FF5A12 in linear light

    'mat2 rot(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}',

    /* (2,3) torus knot: two strands per meridian cross-section, phase 1.5*theta.
       Cross-section distance is an upper bound on true distance -> 0.55 Lipschitz. */
    'float sdKnot(vec3 p){',
    '  float th=atan(p.z,p.x);',
    '  vec2 cs=vec2(length(p.xz)-0.577,p.y);',
    '  float ph=1.5*th;',
    '  vec2 c=0.288*vec2(cos(ph),sin(ph));',
    '  return (min(length(cs-c),length(cs+c))-0.130)*0.55;',
    '}',

    /* 7-turn helix, nearest-turn lookup in (angle, height), rounded end caps. */
    'float sdCoil(vec3 p){',
    '  float R=0.50,pitch=0.22,tube=0.07;',
    '  float u=atan(p.z,p.x)/TAU;',
    '  float y=p.y+3.5*pitch;',
    '  float v=y/pitch-u;',
    '  float kmin=ceil(-u),kmax=floor(7.0-u);',
    '  float k1=clamp(floor(v+0.5),kmin,kmax);',
    '  float k2=clamp(floor(v),kmin,kmax);',
    '  vec2 cs=vec2(length(p.xz)-R,y);',
    '  float d=length(cs-vec2(0.0,pitch*(u+k1)))-tube;',
    '  d=min(d,length(cs-vec2(0.0,pitch*(u+k2)))-tube);',
    '  d=min(d,length(vec3(p.x-R,y,p.z))-tube);',
    '  d=min(d,length(vec3(p.x-R,y-7.0*pitch,p.z))-tube);',
    '  return d*0.55;',
    '}',

    'float sdDamper(vec3 p){',
    '  vec2 b=vec2(length(p.xz)-0.19,abs(p.y)-0.58);',
    '  float body=min(max(b.x,b.y),0.0)+length(max(b,0.0))-0.035;',
    '  float rod=length(vec2(length(p.xz),max(abs(p.y)-0.90,0.0)))-0.05;',
    '  return min(body,rod);',
    '}',

    // returns (distance, material)  material 0 = glossy body, 1 = faint damper
    'vec2 map(vec3 p){',
    '  vec3 q=uObj*p;',
    '#ifdef COIL',
    '  float a=sdCoil(q), b=sdDamper(q);',
    '  return a<b?vec2(a,0.0):vec2(b,1.0);',
    '#else',
    '  return vec2(sdKnot(q),0.0);',
    '#endif',
    '}',

    'vec3 calcNormal(vec3 p){',
    '  vec2 e=vec2(1.0,-1.0)*0.0013;',
    '  return normalize(e.xyy*map(p+e.xyy).x+e.yyx*map(p+e.yyx).x+',
    '                   e.yxy*map(p+e.yxy).x+e.xxx*map(p+e.xxx).x);',
    '}',

    'float calcAO(vec3 p,vec3 n){',
    '  float occ=0.0,sca=1.0;',
    '  for(int i=0;i<5;i++){',
    '    float h=0.02+0.09*float(i);',
    '    occ+=(h-map(p+n*h).x)*sca;',
    '    sca*=0.72;',
    '  }',
    '  return clamp(1.0-2.2*occ,0.0,1.0);',
    '}',

    /* Procedural studio environment: dark room, one soft key softbox,
       one accent strip behind-right, faint floor bounce. r = roughness blur. */
    'vec3 env(vec3 d,float r){',
    '  float up=d.y*0.5+0.5;',
    '  vec3 c=mix(vec3(0.003,0.003,0.005),vec3(0.028,0.031,0.038),up*up);',
    '  float s1=max(dot(d,normalize(vec3(-0.55,0.75,0.55))),0.0);',
    '  c+=vec3(1.0,0.97,0.92)*pow(s1,mix(26.0,2.0,r))*mix(1.5,0.25,r);',
    '  c+=vec3(0.30,0.34,0.42)*pow(s1,3.0)*0.08;',
    '  float s2=max(dot(d,normalize(vec3(0.90,0.05,-0.45))),0.0);',
    '  c+=ACC*pow(s2,mix(9.0,2.0,r))*mix(2.4,0.6,r);',
    '  c+=vec3(0.016,0.017,0.021)*pow(max(-d.y,0.0),2.0);',
    '  return c;',
    '}',

    'vec3 specBRDF(vec3 n,vec3 v,vec3 l,float rough,vec3 F0){',
    '  vec3 h=normalize(v+l);',
    '  float NoL=max(dot(n,l),0.0),NoV=max(dot(n,v),1e-4);',
    '  float NoH=max(dot(n,h),0.0),VoH=max(dot(v,h),0.0);',
    '  float a=max(rough*rough,0.0025),a2=a*a;',
    '  float dd=NoH*NoH*(a2-1.0)+1.0;',
    '  float D=a2/(PI*dd*dd);',
    '  float k=a*0.5;',
    '  float G=(NoL/(NoL*(1.0-k)+k))*(NoV/(NoV*(1.0-k)+k));',
    '  vec3 F=F0+(vec3(1.0)-F0)*pow(1.0-VoH,5.0);',
    '  return D*G*F*NoL/(4.0*NoL*NoV+1e-4);',
    '}',

    'vec3 shade(vec3 p,vec3 rd,float mat){',
    '  vec3 n=calcNormal(p), v=-rd;',
    '  float ao=calcAO(p,n);',
    '  float NoV=max(dot(n,v),1e-4);',
    '  float fres=pow(1.0-NoV,5.0);',
    '  float rough = mat<0.5 ? 0.16 : 0.45;',
    '  vec3 albedo = mat<0.5 ? vec3(0.020,0.019,0.018) : vec3(0.013);',
    '  vec3 F0=vec3(0.055);',
    '  vec3 L1=normalize(vec3(-0.55,0.75,0.55));',
    '  vec3 L2=normalize(vec3( 0.90,0.05,-0.45));',
    '  vec3 C1=vec3(1.0,0.96,0.90)*2.4;',
    '  vec3 C2=ACC*6.0;',
    '  vec3 col=vec3(0.0);',
    '  col+=albedo*C1*max(dot(n,L1),0.0)*ao;',
    '  col+=specBRDF(n,v,L1,rough,F0)*C1*ao;',
    '  col+=albedo*C2*max(dot(n,L2),0.0)*ao;',
    '  col+=specBRDF(n,v,L2,rough*0.8,F0)*C2*ao;',
    '  col+=albedo*vec3(0.10,0.12,0.16)*max(dot(n,normalize(vec3(0.2,-0.7,0.5))),0.0)*ao;',
    '  vec3 F=F0+(vec3(1.0)-F0)*fres;',
    '  col+=env(reflect(rd,n),rough)*F*mix(ao,1.0,0.5);',
    '  col+=ACC*pow(1.0-NoV,3.0)*(0.35+0.9*max(dot(n,L2),0.0))*ao*1.1;',
    '  return col;',
    '}',

    'vec3 display(vec3 c){',
    '  c=vec3(1.0)-exp(-max(c,0.0)*1.25);',   // exposure tonemap, keeps blacks deep
    '  return pow(c,vec3(1.0/2.2));',
    '}',

    'void main(){',
    '  float aspect=uRes.x/uRes.y;',
    '  vec2 sp=(gl_FragCoord.xy/uRes-uCenter)*vec2(aspect,1.0);',
    '  float D=5.0;',
    '  float fl=0.275*min(aspect,1.0)*sqrt(D*D-1.0);', // object = 55% of short side
    '  vec3 ro=vec3(0.0,0.0,D);',
    '  vec3 rd=normalize(vec3(sp,-fl));',
    '  float yaw=uPointer.x*0.07, pit=uPointer.y*0.05;',
    '  ro.xz=rot(yaw)*ro.xz; rd.xz=rot(yaw)*rd.xz;',
    '  ro.yz=rot(pit)*ro.yz; rd.yz=rot(pit)*rd.yz;',
    '  float px=1.0/(uRes.y*fl);',           // pixel footprint per unit depth
    '  vec3 outC=vec3(0.0); float outA=0.0;',
    '  float b=dot(ro,rd), cc=dot(ro,ro)-1.3225, h=b*b-cc;', // bounding sphere r=1.15
    '  if(h>0.0){',
    '    float sh=sqrt(h);',
    '    float t=max(-b-sh,0.0), tmax=-b+sh;',
    '    float minH=1e9, tHit=t, minD=1e9;',
    '    bool hit=false;',
    '    for(int i=0;i<96;i++){',
    '      float d=map(ro+rd*t).x;',
    '      minD=min(minD,d);',
    '      float hh=d/(px*t);',
    '      if(hh<minH){minH=hh;tHit=t;}',
    '      if(d<px*t*0.3){hit=true;tHit=t;break;}',
    '      t+=d;',
    '      if(t>tmax)break;',
    '    }',
    '    float cov=hit?1.0:clamp(1.0-minH,0.0,1.0);',
    '    cov=cov*cov*(3.0-2.0*cov);',        // analytic silhouette antialiasing
    '    if(cov>0.002){',
    '      vec3 p=ro+rd*tHit;',
    '      float mat=map(p).y;',
    '      float a=cov*(mat<0.5?1.0:0.55);', // damper reads as a faint ghost
    '      outC+=display(shade(p,rd,mat))*a;',
    '      outA+=a;',
    '    }',
    '    if(!hit){',
    '      float md=max(minD,0.0);',
    '      float g=exp(-md*9.0), g2=exp(-md*2.5);',
    '      float perp=sqrt(max(dot(ro,ro)-b*b,0.0));',
    '      float fade=smoothstep(1.15,0.85,perp);', // no hard sphere edge
    '      float ga=clamp(g*0.35+g2*0.07,0.0,0.85)*fade*(1.0-outA);',
    '      outC+=display(ACC*(g*0.55+g2*0.12))*ga;',
    '      outA+=ga;',
    '    }',
    '  }',
    '  gl_FragColor=vec4(clamp(outC,0.0,1.0),clamp(outA,0.0,1.0));', // premultiplied
    '}'
  ].join('\n');

  /* ------------------------------------------------------------- utilities */
  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }

  function compile(gl, type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      gl.deleteShader(s);
      return null;
    }
    return s;
  }

  /* -------------------------------------------------------------- renderer */
  function Hero(canvas) {
    if (canvas.__qwHero) return;
    canvas.__qwHero = true;
    canvas.setAttribute('aria-hidden', 'true');

    var shape = canvas.getAttribute('data-shape') === 'coil' ? 'coil' : 'knot';
    var frag  = (shape === 'coil' ? '#define COIL\n' : '#define KNOT\n') + FRAG_BODY;

    var gl = null, prog = null, buf = null, uni = {}, lost = false, ready = false;
    var cssW = 0, cssH = 0, quality = Q_START, rect = null;
    var raf = 0, last = 0, time = 0, ema = 16.7, frames = 0, cooldown = 0;
    var inView = true, pageVisible = !document.hidden;
    var ptrX = 0, ptrY = 0, tgtX = 0, tgtY = 0;
    var objMat = new Float32Array(9);
    var mq = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;

    function reduced() { return !!(mq && mq.matches); }

    function initGL() {
      var opts = {
        alpha: true, premultipliedAlpha: true, antialias: false,
        depth: false, stencil: false, preserveDrawingBuffer: false,
        powerPreference: 'high-performance'
      };
      gl = canvas.getContext('webgl', opts) || canvas.getContext('experimental-webgl', opts);
      if (!gl) return false;

      var vs = compile(gl, gl.VERTEX_SHADER, VERT);
      var fs = compile(gl, gl.FRAGMENT_SHADER, frag);
      if (!vs || !fs) return false;
      prog = gl.createProgram();
      gl.attachShader(prog, vs); gl.attachShader(prog, fs);
      gl.bindAttribLocation(prog, 0, 'aPos');
      gl.linkProgram(prog);
      gl.deleteShader(vs); gl.deleteShader(fs);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return false;
      canvas.setAttribute('data-renderer', 'webgl');   // hero.js (2D fallback) stands down

      buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
      gl.useProgram(prog);
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
      gl.disable(gl.DEPTH_TEST);
      gl.disable(gl.BLEND);
      gl.clearColor(0, 0, 0, 0);

      uni.res = gl.getUniformLocation(prog, 'uRes');
      uni.ctr = gl.getUniformLocation(prog, 'uCenter');
      uni.ptr = gl.getUniformLocation(prog, 'uPointer');
      uni.tim = gl.getUniformLocation(prog, 'uTime');
      uni.obj = gl.getUniformLocation(prog, 'uObj');
      return true;
    }

    function resize() {
      rect = canvas.getBoundingClientRect();
      cssW = Math.max(1, Math.round(rect.width));
      cssH = Math.max(1, Math.round(rect.height));
      var dpr = Math.min(window.devicePixelRatio || 1, DPR_CAP);
      var s = Math.min(dpr, Math.sqrt(MAX_PIXELS / (cssW * cssH)));
      s = Math.max(0.35, s * quality);
      var w = Math.max(1, Math.round(cssW * s));
      var h = Math.max(1, Math.round(cssH * s));
      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;
    }

    function draw(t, px, py) {
      if (!ready || lost || !cssW || !cssH) return;
      var tilt = shape === 'knot' ? 0.45 + 0.07 * Math.sin(t * 0.11) : 0.10;
      var spin = t * (shape === 'knot' ? 0.16 : 0.13);
      var a = -tilt, b = -spin;
      var ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b);
      // column-major Ry(-spin) * Rx(-tilt)
      objMat[0] = cb;        objMat[1] = 0;   objMat[2] = -sb;
      objMat[3] = sb * sa;   objMat[4] = ca;  objMat[5] = cb * sa;
      objMat[6] = sb * ca;   objMat[7] = -sa; objMat[8] = cb * ca;

      var wide = cssW >= BREAKPOINT;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.useProgram(prog);
      gl.uniform2f(uni.res, canvas.width, canvas.height);
      gl.uniform2f(uni.ctr, wide ? 0.45 : 0.62, wide ? 0.54 : 0.64); // GL y = 1 - cssY
      gl.uniform2f(uni.ptr, px, py);
      gl.uniform1f(uni.tim, t);
      gl.uniformMatrix3fv(uni.obj, false, objMat);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }

    function drawStatic() {
      resize();
      draw(STATIC_TIME[shape], 0, 0);
    }

    function shouldRun() {
      return ready && !lost && inView && pageVisible && !reduced();
    }

    function frame(now) {
      raf = 0;
      if (!shouldRun()) { last = 0; return; }
      var dtMs = last ? now - last : 16.7;
      last = now;
      var dt = Math.min(dtMs / 1000, 0.05);
      time += dt;

      var k = Math.min(1, dt * 5);
      ptrX += (tgtX - ptrX) * k;
      ptrY += (tgtY - ptrY) * k;

      draw(time, ptrX, ptrY);

      // adaptive internal resolution (hysteresis + cooldown)
      ema = ema * 0.9 + Math.min(dtMs, 60) * 0.1;
      frames++;
      if (cooldown > 0) cooldown--;
      else if (frames > 45) {
        if (ema > 19.5 && quality > Q_MIN) {
          quality = Math.max(Q_MIN, quality - 0.12); resize(); cooldown = 90; ema = 16.7;
        } else if (ema < 13.0 && quality < Q_MAX) {
          quality = Math.min(Q_MAX, quality + 0.06); resize(); cooldown = 90; ema = 16.7;
        }
      }
      raf = requestAnimationFrame(frame);
    }

    function start() {
      if (raf || !shouldRun()) return;
      last = 0;
      raf = requestAnimationFrame(frame);
    }
    function stop() {
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      last = 0;
    }
    function sync() {
      if (reduced()) { stop(); drawStatic(); }
      else if (shouldRun()) start();
      else stop();
    }

    /* ------------------------------------------------------------- wiring */
    ready = initGL();
    if (!ready) return; // graceful: CSS background stays, nothing is drawn

    canvas.addEventListener('webglcontextlost', function (e) {
      e.preventDefault(); lost = true; stop();
    }, false);
    canvas.addEventListener('webglcontextrestored', function () {
      lost = false; ready = initGL(); resize(); sync();
    }, false);

    resize();
    time = STATIC_TIME[shape];
    sync();

    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        resize();
        if (reduced() || !shouldRun()) drawStatic();
      }).observe(canvas);
    } else {
      window.addEventListener('resize', function () {
        resize();
        if (reduced() || !shouldRun()) drawStatic();
      }, { passive: true });
    }

    if (window.IntersectionObserver) {
      new IntersectionObserver(function (entries) {
        inView = entries[entries.length - 1].isIntersecting;
        sync();
      }, { rootMargin: '120px' }).observe(canvas);
    }

    document.addEventListener('visibilitychange', function () {
      pageVisible = !document.hidden;
      sync();
    }, false);

    if (mq) {
      var onMQ = function () { sync(); };
      if (mq.addEventListener) mq.addEventListener('change', onMQ);
      else if (mq.addListener) mq.addListener(onMQ);
    }

    function refreshRect() { rect = canvas.getBoundingClientRect(); }
    window.addEventListener('scroll', refreshRect, { passive: true });

    window.addEventListener('pointermove', function (e) {
      if (reduced() || !rect || !rect.width) return;
      tgtX = clamp(((e.clientX - rect.left) / rect.width) * 2 - 1, -1, 1);
      tgtY = clamp(((e.clientY - rect.top) / rect.height) * 2 - 1, -1, 1);
    }, { passive: true });

    window.addEventListener('pointerleave', function () { tgtX = 0; tgtY = 0; }, { passive: true });
    window.addEventListener('blur', function () { tgtX = 0; tgtY = 0; }, false);
  }

  /* ----------------------------------------------------------------- boot */
  function boot() {
    var list = document.querySelectorAll('canvas.hero-canvas');
    for (var i = 0; i < list.length; i++) {
      try { new Hero(list[i]); } catch (err) { /* never break the page */ }
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
