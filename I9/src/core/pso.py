"""
Particle Swarm Optimization (PSO) com paralelização para otimização do pipeline I9.
"""

from __future__ import annotations

import random
from multiprocessing import Pool
from typing import Callable, List, Tuple

import numpy as np


class Particle:
    """Partícula do PSO."""
    
    def __init__(self, position: np.ndarray, velocity: np.ndarray):
        self.position = position
        self.velocity = velocity
        self.best_position = position.copy()
        self.best_fitness = -np.inf


class PSO:
    """Particle Swarm Optimization com paralelização.
    
    Args:
        fitness_fn: função de aptidão (recebe lista de floats, retorna float)
        bounds: lista de (min, max) para cada dimensão
        n_particles: número de partículas
        n_iterations: número de iterações
        w: peso de inércia
        c1: coeficiente cognitivo (pessoal)
        c2: coeficiente social (global)
        n_workers: número de workers paralelos
    """
    
    def __init__(
        self,
        fitness_fn: Callable[[List[float]], float],
        bounds: List[Tuple[float, float]],
        n_particles: int = 30,
        n_iterations: int = 100,
        w: float = 0.7,
        c1: float = 1.5,
        c2: float = 1.5,
        n_workers: int = 4,
    ):
        self.fitness_fn = fitness_fn
        self.bounds = bounds
        self.n_particles = n_particles
        self.n_iterations = n_iterations
        self.w = w
        self.c1 = c1
        self.c2 = c2
        self.n_workers = n_workers
        
        # Extrai limites
        self.lower_bounds = np.array([b[0] for b in bounds])
        self.upper_bounds = np.array([b[1] for b in bounds])
    
    def _initialize_particles(self) -> List[Particle]:
        """Inicializa partículas com posições e velocidades aleatórias."""
        particles = []
        for _ in range(self.n_particles):
            # Posição aleatória dentro dos limites
            position = np.random.uniform(self.lower_bounds, self.upper_bounds)
            # Velocidade aleatória pequena
            velocity = np.random.uniform(-0.1, 0.1, size=len(self.bounds))
            particles.append(Particle(position, velocity))
        return particles
    
    def _evaluate_fitness(self, positions: List[np.ndarray]) -> List[float]:
        """Avalia fitness de múltiplas posições em paralelo."""
        if self.n_workers <= 1:
            # Execução sequencial
            return [self.fitness_fn(pos.tolist()) for pos in positions]
        
        # Execução paralela
        with Pool(self.n_workers) as pool:
            results = pool.map(self.fitness_fn, [pos.tolist() for pos in positions])
        return results
    
    def optimize(self) -> Tuple[List[float], float]:
        """Executa otimização PSO.
        
        Returns:
            (melhor_posicao, melhor_fitness)
        """
        # 1. Inicializa partículas
        particles = self._initialize_particles()
        global_best_position = None
        global_best_fitness = -np.inf
        
        for iteration in range(self.n_iterations):
            # 2. Avalia fitness em paralelo
            positions = [p.position for p in particles]
            fitness_values = self._evaluate_fitness(positions)
            
            # 3. Atualiza melhores posições pessoais e globais
            for i, (particle, fitness) in enumerate(zip(particles, fitness_values)):
                # Atualiza melhor pessoal
                if fitness > particle.best_fitness:
                    particle.best_fitness = fitness
                    particle.best_position = particle.position.copy()
                
                # Atualiza melhor global
                if fitness > global_best_fitness:
                    global_best_fitness = fitness
                    global_best_position = particle.position.copy()
            
            # 4. Atualiza velocidades e posições
            for particle in particles:
                r1 = np.random.rand(len(self.bounds))
                r2 = np.random.rand(len(self.bounds))
                
                # Componente cognitivo (pessoal)
                cognitive = self.c1 * r1 * (particle.best_position - particle.position)
                
                # Componente social (global)
                social = self.c2 * r2 * (global_best_position - particle.position)
                
                # Atualiza velocidade
                particle.velocity = self.w * particle.velocity + cognitive + social
                
                # Atualiza posição
                particle.position = particle.position + particle.velocity
                
                # Clip aos limites
                particle.position = np.clip(
                    particle.position, self.lower_bounds, self.upper_bounds
                )
            
            # Log do progresso
            print(f"Iteration {iteration + 1}/{self.n_iterations}: Best F1-Macro = {global_best_fitness:.4f}")
        
        return global_best_position.tolist(), global_best_fitness
