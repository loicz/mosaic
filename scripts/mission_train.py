#!/usr/bin/env python3
"""Reproducible tiny local lidar risk model. Synthetic training, no cloud API."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np


def samples(seed, count):
    rng = np.random.default_rng(seed)
    angles = np.linspace(-.55, .55, 9)
    data, labels = [], []
    for _ in range(count):
        # Ray intersections with randomly placed circles. The independently
        # computed swept vehicle corridor supplies the training label.
        centers = rng.uniform([.3, -3], [8, 3], (rng.integers(1, 8), 2))
        radii = rng.uniform(.12, 1.1, len(centers))
        rays = np.stack([np.cos(angles), np.sin(angles)], axis=1)
        projection = centers @ rays.T
        perpendicular = (centers ** 2).sum(axis=1)[:, None] - projection ** 2
        disc = radii[:, None] ** 2 - perpendicular
        hits = projection - np.sqrt(np.maximum(0, disc))
        hits[(disc < 0) | (hits < .05)] = 8
        depth = np.minimum(8, hits.min(axis=0))
        # Risk label is derived from physical swept-disc geometry, not model
        # outputs. Includes finite-sensor ambiguity, reflected in held-out score.
        corridor = np.abs(centers[:, 1]) < radii + .43
        ahead = centers[:, 0] - np.sqrt(np.maximum(0, (radii+.43)**2 - centers[:, 1]**2))
        free = float(np.min(ahead[corridor])) if np.any(corridor) else 8
        label = 2 if free < 1.1 else 1 if free < 2.6 else 0
        data.append(np.clip(depth+rng.normal(0, .035, 9), 0, 8)/4-1)
        labels.append(label)
    return np.asarray(data), np.asarray(labels)


def train(output):
    rng = np.random.default_rng(4103)
    x, y = samples(4103, 18000)
    vx, vy = samples(9817, 4000)
    w1 = rng.normal(0, .22, (24, 9)); b1 = np.zeros(24)
    w2 = rng.normal(0, .22, (3, 24)); b2 = np.zeros(3)
    weights = [w1, b1, w2, b2]
    moments = [np.zeros_like(w) for w in weights]
    velocities = [np.zeros_like(w) for w in weights]
    step = 0
    for _ in range(65):
        order = rng.permutation(len(x))
        for indices in np.array_split(order, 60):
            bx, by = x[indices], y[indices]
            h = np.tanh(bx @ w1.T + b1)
            logits = h @ w2.T + b2
            p = np.exp(logits-logits.max(axis=1, keepdims=True))
            p /= p.sum(axis=1, keepdims=True)
            p[np.arange(len(by)), by] -= 1
            p /= len(by)
            dh = (p @ w2) * (1-h*h)
            gradients = [dh.T @ bx, dh.sum(axis=0), p.T @ h, p.sum(axis=0)]
            step += 1
            for w, m, v, grad in zip(weights, moments, velocities, gradients):
                m[:] = .9*m + .1*grad
                v[:] = .999*v + .001*grad*grad
                w -= .002*(m/(1-.9**step))/(np.sqrt(v/(1-.999**step))+1e-8)
    predictions = (np.tanh(vx @ w1.T+b1) @ w2.T+b2).argmax(axis=1)
    confusion = np.zeros((3, 3), dtype=int)
    for label, prediction in zip(vy, predictions):
        confusion[label, prediction] += 1
    document = dict(schema='mosaic.local-model.v1', id='lidar-corridor-4103-v1',
                    inputs=9, hidden=24, outputs=3, classes=['open', 'caution', 'blocked'],
                    w1=w1.ravel().tolist(), b1=b1.tolist(), w2=w2.ravel().tolist(), b2=b2.tolist(),
                    training=dict(seed=4103, samples=len(x), epochs=65, source='scripts/mission_train.py'),
                    evaluation=dict(seed=9817, samples=len(vx), accuracy=float(np.mean(predictions == vy)),
                                    confusion=confusion.tolist()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, separators=(',', ':'))+'\n')
    print(json.dumps(document['evaluation']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('models/mission-lidar.json'))
    train(parser.parse_args().output)
