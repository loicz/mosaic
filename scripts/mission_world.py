#!/usr/bin/env python3
"""Generate the actual Gazebo physics world; never used as a controller input."""
from __future__ import annotations
import json
import copy
from pathlib import Path
import xml.etree.ElementTree as ET


def plugin(parent, filename, name, **settings):
    element = ET.SubElement(parent, 'plugin', filename=filename, name='gz::sim::systems::' + name)
    for key, value in settings.items():
        ET.SubElement(element, key).text = str(value)
    return element


def box(world, name, bounds, height, color='0.34 0.43 0.52 1'):
    x, y, w, h = bounds
    model = ET.SubElement(world, 'model', name=name)
    ET.SubElement(model, 'static').text = 'true'
    ET.SubElement(model, 'pose').text = f'{x+w/2} {y+h/2} {height/2} 0 0 0'
    link = ET.SubElement(model, 'link', name='body')
    for kind in ('collision', 'visual'):
        element = ET.SubElement(link, kind, name=kind)
        ET.SubElement(ET.SubElement(ET.SubElement(element, 'geometry'), 'box'), 'size').text = f'{w} {h} {height}'
        if kind == 'visual':
            material = ET.SubElement(element, 'material')
            ET.SubElement(material, 'ambient').text = color
            ET.SubElement(material, 'diffuse').text = color


def generate(scene: dict, output: Path, models: Path, count: int | None = None) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    # Retain upstream inertias, collisions, motor dynamics and sensor models.
    # Render collision geometry instead of cosmetic CAD meshes, which avoids
    # wasting software-renderer time on six aircraft's logos and motor details.
    local_models = output / 'models'
    for name in ('x500', 'x500_base'):
        target = local_models / name
        target.mkdir(parents=True, exist_ok=True)
        document = ET.parse(models/name/'model.sdf')
        if name == 'x500_base':
            for link in document.findall('.//link'):
                for visual in link.findall('visual'): link.remove(visual)
                for index, collision in enumerate(link.findall('collision')):
                    visual = ET.SubElement(link,'visual',name=f'physics_proxy_{index}')
                    for field in ('pose','geometry'):
                        element=collision.find(field)
                        if element is not None: visual.append(copy.deepcopy(element))
                    material=ET.SubElement(visual,'material')
                    ET.SubElement(material,'diffuse').text='.35 .55 .58 1'
        ET.indent(document)
        document.write(target/'model.sdf',encoding='unicode',xml_declaration=True)
        (target/'model.config').write_text((models/name/'model.config').read_text())
    root = ET.Element('sdf', version='1.9')
    world = ET.SubElement(root, 'world', name='mosaic')
    physics = ET.SubElement(world, 'physics', name='physics', type='ignored')
    ET.SubElement(physics, 'max_step_size').text = '0.004'
    ET.SubElement(physics, 'real_time_factor').text = '1'
    ET.SubElement(world, 'gravity').text = '0 0 -9.80665'
    ET.SubElement(world, 'magnetic_field').text = '6e-6 2.3e-5 -4.2e-5'
    for filename, name in [('physics', 'Physics'), ('user-commands', 'UserCommands'),
                           ('scene-broadcaster', 'SceneBroadcaster'), ('imu', 'Imu'),
                           ('air-pressure', 'AirPressure'), ('magnetometer', 'Magnetometer')]:
        plugin(world, 'gz-sim-' + filename + '-system', name)
    plugin(world, 'gz-sim-sensors-system', 'Sensors', render_engine='ogre2')
    visual = ET.SubElement(world, 'scene')
    ET.SubElement(visual, 'ambient').text = '0.7 0.7 0.7 1'
    light = ET.SubElement(world, 'light', name='sun', type='directional')
    ET.SubElement(light, 'direction').text = '0.3 0.2 -1'
    ET.SubElement(light, 'diffuse').text = '0.8 0.8 0.8 1'
    box(world, 'ground', [-5, -5, 36, 29], .1, '0.18 0.22 0.27 1')
    for i, bounds in enumerate(scene['walls']):
        box(world, f'wall_{i}', bounds, 3)
    for obstacle in scene['obstacles']:
        box(world, obstacle['id'], obstacle['box'], obstacle['height'], '0.85 0.45 0.14 1')
    # Perching mechanism is represented by passive supporting surfaces. Physical
    # contact/landing is simulated; no fictitious adhesive strength is claimed.
    for site in scene['sites']:
        x, y = site['position']
        box(world, 'support_' + site['id'], [x-.6, y-.6, 1.2, 1.2], .5, '0.15 0.5 0.47 1')
    for drone in scene['drones'][:count]:
        model = ET.SubElement(world, 'model', name=drone['id'])
        x, y = drone['dock']
        ET.SubElement(model, 'pose').text = f'{x} {y} .34 0 0 0'
        include = ET.SubElement(model, 'include', merge='true')
        ET.SubElement(include, 'uri').text = str(local_models / 'x500' / 'model.sdf')
        # No GNSS plugin exists in the world; PX4 fuses this explicitly noisy
        # odometry sensor, IMU and barometer. It does not read world pose truth.
        plugin(model, 'gz-sim-odometry-publisher-system', 'OdometryPublisher',
               dimensions=3, odom_publish_frequency=30,
               gaussian_noise=scene['odometry']['noise_stddev'])
        link = ET.SubElement(model, 'link', name='scanner')
        ET.SubElement(link, 'pose').text = '0 0 .55 0 0 0'
        inertial = ET.SubElement(link, 'inertial')
        ET.SubElement(inertial, 'mass').text = '.04'
        inertia = ET.SubElement(inertial, 'inertia')
        for field in ('ixx', 'iyy', 'izz'):
            ET.SubElement(inertia, field).text = '.0001'
        sensor = ET.SubElement(link, 'sensor', name='lidar', type='gpu_lidar')
        ET.SubElement(sensor, 'topic').text = f'/mosaic/{drone["id"]}/scan'
        ET.SubElement(sensor, 'update_rate').text = '10'
        ET.SubElement(sensor, 'always_on').text = 'true'
        lidar = ET.SubElement(sensor, 'lidar')
        horizontal = ET.SubElement(ET.SubElement(lidar, 'scan'), 'horizontal')
        for key, value in [('samples', 180), ('resolution', 1), ('min_angle', -3.14159265), ('max_angle', 3.14159265)]:
            ET.SubElement(horizontal, key).text = str(value)
        limits = ET.SubElement(lidar, 'range')
        for key, value in [('min', .12), ('max', 8), ('resolution', .01)]:
            ET.SubElement(limits, key).text = str(value)
        noise = ET.SubElement(lidar, 'noise')
        ET.SubElement(noise, 'type').text = 'gaussian'
        ET.SubElement(noise, 'stddev').text = '.015'
        joint = ET.SubElement(model, 'joint', name='scanner_mount', type='fixed')
        ET.SubElement(joint, 'parent').text = 'base_link'
        ET.SubElement(joint, 'child').text = 'scanner'
    path = output / 'mission.sdf'
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding='unicode', xml_declaration=True)
    return path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--scene', type=Path, default=Path('config/mission-rescue.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--count', type=int)
    args = parser.parse_args()
    print(generate(json.loads(args.scene.read_text()), args.output, args.models, args.count))
