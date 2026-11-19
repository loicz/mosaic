import * as THREE from './vendor/three/three.module.js';
import {personnelName} from './ui-text.mjs';
import {trailSegments} from './trail-segments.mjs';

const GREEN = 0x28ff78, PALE = 0xc2ffcd, AMBER = 0xffbd69;
const personnelColors = [0xc2ffcd, 0x14ff86, 0x9eff39];

// A bounded nine-tap phosphor halo. Optional and independent of scene state.
class PhosphorPass {
  constructor() {
    this.target = new THREE.WebGLRenderTarget(1, 1, {samples: 2});
    this.scene = new THREE.Scene();
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.material = new THREE.ShaderMaterial({
      depthTest: false, depthWrite: false,
      uniforms: {image: {value: this.target.texture}, texel: {value: new THREE.Vector2(1, 1)}},
      vertexShader: 'varying vec2 uvScene; void main(){uvScene=uv;gl_Position=vec4(position.xy,0.,1.);}',
      fragmentShader: `
        uniform sampler2D image;
        uniform vec2 texel;
        varying vec2 uvScene;
        void main(){
          vec3 base=texture2D(image,uvScene).rgb;
          vec3 glow=vec3(0.);
          for(int x=-1;x<=1;x++)for(int y=-1;y<=1;y++){
            vec3 sampleColor=texture2D(image,uvScene+vec2(float(x),float(y))*texel*2.5).rgb;
            glow+=sampleColor*smoothstep(.15,.7,max(sampleColor.r,max(sampleColor.g,sampleColor.b)));
          }
          gl_FragColor=vec4(base+glow*.075,1.);
          #include <colorspace_fragment>
        }`,
    });
    this.scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.material));
  }
  size(width, height) {
    this.target.setSize(width, height);
    this.material.uniforms.texel.value.set(1 / width, 1 / height);
  }
  render(renderer, scene, camera) {
    renderer.setRenderTarget(this.target);
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    renderer.render(this.scene, this.camera);
  }
}

export class MapView {
  constructor(canvas, container, onSelect) {
    this.canvas = canvas;
    this.container = container;
    this.onSelect = onSelect;
    this.mode = '3d';
    this.effects = true;
    this.renderer = new THREE.WebGLRenderer({canvas, antialias: true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    this.renderer.setClearColor(0x000603, 1);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.phosphor = new PhosphorPass();
    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.Fog(0x000603, 45, 95);
    this.camera = new THREE.PerspectiveCamera(37, 1, .1, 180);
    this.topCamera = new THREE.OrthographicCamera(-18, 18, 13, -13, .1, 100);
    this.center = new THREE.Vector3(13, 0, -9.5);
    this.angle = .38;
    this.distance = 43;
    this.elevation = .83;
    this.environment = new THREE.Group();
    this.scene.add(this.environment);
    this.drones = new Map();
    this.people = new Map();
    this.sites = new Map();
    this.ray = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.drag = null;
    canvas.addEventListener('pointerdown', e => {
      this.drag = {x: e.clientX, y: e.clientY, moved: false};
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener('pointermove', e => {
      if (!this.drag || this.mode === '2d') return;
      const dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) this.drag.moved = true;
      this.angle += dx * .006;
      this.elevation = Math.max(.4, Math.min(1.3, this.elevation + dy * .004));
      this.drag.x = e.clientX; this.drag.y = e.clientY;
    });
    canvas.addEventListener('pointerup', e => {
      if (this.drag && !this.drag.moved) this.pick(e);
      this.drag = null;
    });
    canvas.addEventListener('pointercancel', () => { this.drag = null; });
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      this.distance = Math.max(29, Math.min(65, this.distance + e.deltaY * .03));
    }, {passive: false});
    this.resize = new ResizeObserver(() => this.size());
    this.resize.observe(container);
    this.size();
    let previous = 0;
    const render = time => {
      requestAnimationFrame(render);
      if (document.hidden || time - previous < 1000 / 30) return;
      previous = time;
      const distance = this.distance * Math.max(1, .95 / this.camera.aspect);
      this.camera.position.set(13 + Math.sin(this.angle) * distance * Math.cos(this.elevation), distance * Math.sin(this.elevation), -9.5 + Math.cos(this.angle) * distance * Math.cos(this.elevation));
      this.camera.lookAt(this.center);
      const camera = this.mode === '2d' ? this.topCamera : this.camera;
      if (this.effects) this.phosphor.render(this.renderer, this.scene, camera);
      else this.renderer.render(this.scene, camera);
    };
    requestAnimationFrame(render);
  }
  size() {
    const {width, height} = this.container.getBoundingClientRect();
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    const pixels = this.renderer.getDrawingBufferSize(new THREE.Vector2());
    this.phosphor.size(pixels.x, pixels.y);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    const aspect = width / height, half = Math.max(11.5, 15 / aspect);
    Object.assign(this.topCamera, {left: -half * aspect, right: half * aspect, top: half, bottom: -half});
    this.topCamera.position.set(13, 40, -9.5);
    this.topCamera.up.set(0, 0, -1);
    this.topCamera.lookAt(this.center);
    this.topCamera.updateProjectionMatrix();
  }
  material(color, opacity = 1, wireframe = false) {
    return new THREE.MeshBasicMaterial({color, opacity, transparent: opacity < 1, wireframe});
  }
  cube(x, y, z, w, h, d, color, parent = this.environment, opacity = 1) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), this.material(color, opacity));
    mesh.position.set(x, y, z); parent.add(mesh); return mesh;
  }
  edges(mesh, color = GREEN, opacity = .8) {
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), new THREE.LineBasicMaterial({color, transparent: true, opacity}));
    mesh.add(edges);
  }
  label(text, color = '#70d994', size = .68) {
    const canvas = document.createElement('canvas');
    canvas.width = 384; canvas.height = 64;
    const c = canvas.getContext('2d');
    c.font = '26px "JetBrains Mono NF", monospace';
    c.textAlign = 'center'; c.fillStyle = color; c.fillText(text, 192, 43);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture, transparent: true, depthTest: false}));
    sprite.scale.set(size * 6, size, 1); return sprite;
  }
  build(scene) {
    const floor = this.cube(13, -.15, -9.5, 27, .2, 20, 0x001909);
    this.edges(floor, 0x1c9d4f, .65);
    const grid = new THREE.GridHelper(32, 64, 0x08752f, 0x063719);
    grid.position.set(13, -.035, -9.5); this.environment.add(grid);
    for (const [x, y, w, h] of scene.walls) {
      const wall = this.cube(x + w / 2, .6, -(y + h / 2), w, 1.2, h, 0x005422, this.environment, .32);
      wall.material.depthWrite = false;
      this.edges(wall);
      // Two horizontal wire slices make the scanned volume legible without opaque walls.
      for (const level of [.33, -.33]) {
        const slice = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w, .002, h)), new THREE.LineBasicMaterial({color: GREEN, transparent: true, opacity: .16}));
        slice.position.y = level; wall.add(slice);
      }
    }
    for (const [text, x, y] of [['WEST WING',7,6],['EAST WING',18,6],['CORRIDOR',12,10.5],['RESCUE',18,15],['BASE',12,1.6]]) {
      const label = this.label(text, '#53ad72', .43); label.position.set(x, .13, -y); this.environment.add(label);
    }
    for (const site of scene.sites) {
      const ring = new THREE.Mesh(new THREE.RingGeometry(.42, .46, 4), new THREE.MeshBasicMaterial({color: 0x16853c, side: THREE.DoubleSide, transparent: true, opacity: .8}));
      ring.rotation.x = -Math.PI / 2; ring.rotation.z = Math.PI / 4;
      ring.position.set(site.position[0], .12, -site.position[1]); this.environment.add(ring); this.sites.set(site.id, ring);
    }
    const goal = new THREE.Group();
    const ring = new THREE.Mesh(new THREE.RingGeometry(.65, .7, 4), new THREE.MeshBasicMaterial({color: PALE, side: THREE.DoubleSide}));
    ring.rotation.x = -Math.PI / 2; ring.rotation.z = Math.PI / 4; goal.add(ring);
    const targetLabel = this.label('RALLY', '#c2ffcd', .5); targetLabel.position.y = 1.25; goal.add(targetLabel);
    goal.position.set(scene.destination.position[0], .15, -scene.destination.position[1]); this.environment.add(goal);
    if (scene.evacuation) {
      for (const name of ['primary', 'alternate']) {
        const point = scene.evacuation[name].route.at(-1);
        const safe = this.cube(point[0], .08, -point[1], 1.8, .04, 1.8, GREEN, this.environment, .18);
        this.edges(safe, PALE);
        const label = this.label(name === 'primary' ? 'SAFE / SOUTH' : 'SAFE / WEST', '#c2ffcd', .38);
        label.position.set(point[0], .85, -point[1]); this.environment.add(label);
      }
      const [x, y, w, h] = scene.evacuation.closure.box;
      this.closure = this.cube(x+w/2, .6, -(y+h/2), w, 1.2, h, AMBER, this.environment, .7);
      this.edges(this.closure, AMBER); this.closure.visible = false;
      this.exitRoute = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({color: AMBER, dashSize: .3, gapSize: .2}));
      this.environment.add(this.exitRoute);
      this.routeLabel = this.label('PLANNED EXIT ROUTE', '#ffbd69', .4);
      this.routeLabel.position.set(11, .7, -3); this.environment.add(this.routeLabel);
      this.routeLabel.visible = false;
    }
    for (const d of scene.drones) {
      const group = new THREE.Group();
      const body = this.cube(0, 0, 0, .32, .13, .3, 0x075c2b, group); this.edges(body, PALE);
      this.cube(0, 0, 0, .85, .035, .075, GREEN, group).rotation.y = .75;
      this.cube(0, 0, 0, .85, .035, .075, GREEN, group).rotation.y = -.75;
      for (const x of [-.27, .27]) for (const z of [-.27, .27]) {
        const rotor = new THREE.Mesh(new THREE.TorusGeometry(.17, .019, 5, 20), this.material(GREEN));
        rotor.rotation.x = -Math.PI / 2; rotor.position.set(x, .04, z); group.add(rotor);
      }
      const label = this.label(d.id, '#65ffa0', .4); label.position.y = .65; group.add(label);
      group.position.set(d.dock[0], .35, -d.dock[1]); this.scene.add(group);
      group.traverse(o => { if (o.material) { o.userData.opacity = o.material.opacity; if (!o.isSprite) o.userData.color = o.material.color.getHex(); } });
      this.drones.set(d.id, {group});
    }
    scene.roster.forEach((person, index) => {
      const color = personnelColors[index % personnelColors.length];
      const group = new THREE.Group();
      const body = new THREE.Mesh(new THREE.CapsuleGeometry(.17, .35, 4, 8), this.material(color, .9, true));
      body.position.y = .45; group.add(body);
      const head = new THREE.Mesh(new THREE.SphereGeometry(.16, 8, 6), this.material(color, .9, true));
      head.position.y = .94; group.add(head);
      const aura = new THREE.Mesh(new THREE.RingGeometry(.95, 1, 48), new THREE.MeshBasicMaterial({color, side: THREE.DoubleSide, transparent: true, opacity: .4}));
      aura.rotation.x = -Math.PI / 2; aura.position.y = .16; group.add(aura);
      const name = personnelName(person).split(' / ').at(-1);
      const label = this.label(`${person.id} / ${name}`, '#c2ffcd', .48); label.position.y = 1.6; group.add(label);
      const reticle = new THREE.Mesh(new THREE.RingGeometry(.6, .65, 4), new THREE.MeshBasicMaterial({color: PALE, side: THREE.DoubleSide}));
      reticle.rotation.x = -Math.PI / 2; reticle.rotation.z = Math.PI / 4; reticle.position.y = .19; group.add(reticle);
      group.userData.person = person.id; body.userData.person = person.id; head.userData.person = person.id;
      group.visible = false; this.scene.add(group);
      const material = index === 0 ? new THREE.LineBasicMaterial({color, transparent: true, opacity: .85}) : new THREE.LineDashedMaterial({color, transparent: true, opacity: .85, dashSize: index === 1 ? .3 : .08, gapSize: .13});
      const line = new THREE.LineSegments(new THREE.BufferGeometry(), material); this.scene.add(line);
      this.people.set(person.id, {group, aura, reticle, line, body, head, color});
    });
  }
  update(state, selected) {
    if (this.closure) this.closure.visible = Boolean(state.evacuation?.blocked);
    if (this.exitRoute) {
      const route = state.evacuation?.plan?.route;
      const key = JSON.stringify(route || []);
      this.exitRoute.visible = this.routeLabel.visible = Boolean(route);
      if (key !== this.exitRouteKey) {
        this.exitRouteKey = key; this.exitRoute.geometry.dispose();
        this.exitRoute.geometry = new THREE.BufferGeometry().setFromPoints((route || []).map(([x,y]) => new THREE.Vector3(x,.15,-y)));
        this.exitRoute.computeLineDistances();
      }
    }
    for (const item of this.people.values()) { item.group.visible = false; item.line.visible = false; }
    for (const d of state.drones) {
      const item = this.drones.get(d.id); if (!item) continue;
      const p = d.position, dock = state.scene.drones.find(v => v.id === d.id)?.dock;
      if (p) item.group.position.set(p[0], Math.max(.33, p[2] + .25), -p[1]);
      else if (dock) item.group.position.set(dock[0], .35, -dock[1]);
      item.group.traverse(o => {
        if (!o.material) return;
        o.material.transparent = true; o.material.opacity = o.userData.opacity * (d.stale ? .3 : 1);
        if (o.userData.color !== undefined) o.material.color.setHex(d.state === 'radio_failed' ? AMBER : o.userData.color);
      });
    }
    for (const p of state.people) {
      const item = this.people.get(p.id); if (!item || !p.position) continue;
      const current = p.status === 'current';
      item.group.visible = true; item.group.position.set(p.position[0], 0, -p.position[1]);
      item.aura.scale.setScalar(Math.min(2.5, Math.max(.35, p.allowance || .7)));
      item.aura.material.opacity = current ? .4 : .2;
      item.aura.material.color.setHex(current ? item.color : AMBER);
      item.body.material.opacity = item.head.material.opacity = current ? .9 : .3;
      item.reticle.visible = p.id === selected;
      item.group.scale.setScalar(p.id === selected ? 1.12 : 1);
      item.line.geometry.dispose();
      item.line.geometry = new THREE.BufferGeometry().setFromPoints(trailSegments(p.trail, state.scene.walls).map(([x, y]) => new THREE.Vector3(x, .2, -y)));
      if (item.line.material.isLineDashedMaterial) item.line.computeLineDistances();
      item.line.material.opacity = current ? .85 : .25; item.line.visible = true;
    }
    const activeSites=new Set(state.drones.filter(d=>d.anchor&&!d.stale).map(d=>d.target?.id));
    for (const [id, ring] of this.sites) ring.material.color.setHex(activeSites.has(id) ? PALE : state.selected_sites.includes(id) ? GREEN : 0x16853c);
  }
  pick(event) {
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    this.ray.setFromCamera(this.pointer, this.mode === '2d' ? this.topCamera : this.camera);
    const objects = [...this.people.values()].filter(p => p.group.visible).map(p => p.group);
    const person = this.ray.intersectObjects(objects, true).find(h => h.object.userData.person);
    if (person) this.onSelect(person.object.userData.person);
  }
}
