from bindings import *
import random
import math
import rod.conversions as conversions
import networkx as nx
import sklearn.neighbors
import numpy as np
import time

from rod.solvers.collision_detection import Collision_detector

# The number of nearest neighbors each vertex will try to connect to
K = 15

# the radius by which the rod will be expanded
epsilon = FT(0.1)

# Calculate the scene's bounding box
def calc_bbox(obstacles):
    X = []
    Y = []
    for poly in obstacles:
        for point in poly.vertices():
            X.append(point.x())
            Y.append(point.y())
    min_x = min(X)
    max_x = max(X)
    min_y = min(Y)
    max_y = max(Y)

    return min_x, max_x, min_y, max_y

# Convert CGALPY's Point_d object into an array of doubles
def point_d_to_arr(p: Point_d):
    return [p[i].to_double() for i in range(p.dimension())]


def generate_path(length, obstacles, origin, destination, argument, writer, isRunning):
    t0 = time.perf_counter()
    # Parsing of arguments
    path = []
    try:
        num_landmarks = int(argument)
    except Exception as e:
        print("argument is not an integer", file=writer)
        return path

    polygons = [conversions.tuples_list_to_polygon_2(p) for p in obstacles]
    bbox = calc_bbox(polygons)
    x_range = (bbox[0].to_double(), bbox[1].to_double())
    y_range = (bbox[2].to_double(), bbox[3].to_double())
    z_range = (0, 2 * math.pi)

    begin = Point_d(3, [FT(origin[0]), FT(origin[1]), FT(origin[2])])
    end = Point_d(3, [FT(destination[0]), FT(destination[1]), FT(destination[2])])

    # Initiate the graph
    G = nx.DiGraph()
    G.add_nodes_from([begin, end])
    points = [begin, end]

    # Initiate the collision detector
    cd = Collision_detector(polygons, [], epsilon)

    # ==== MAIN AREA OF OUR CODE - PRM_GAUSSIAN ====
    # Sample landmarks
    i = 0
    r_x = (x_range[1] - x_range[0]) / 10
    r_y = (y_range[1] - y_range[0]) / 10
    r_z = (z_range[1] - z_range[0]) / 10
    while i < num_landmarks:
        rand_x = FT(random.uniform(x_range[0], x_range[1]))
        rand_y = FT(random.uniform(y_range[0], y_range[1]))
        rand_z = FT(random.uniform(z_range[0], z_range[1]))
        # If valid, add to the graph
        if not cd.is_rod_position_valid(rand_x, rand_y, rand_z, length):
            next_rand_x = FT(min(max(random.gauss(mu=rand_x.to_double(), sigma=r_x), x_range[0]),x_range[1]))
            next_rand_y = FT(min(max(random.gauss(mu=rand_y.to_double(), sigma=r_y), y_range[0]),y_range[1]))
            next_rand_z = FT(min(max(random.gauss(mu=rand_z.to_double(), sigma=r_z), z_range[0]),z_range[1]))
            if cd.is_rod_position_valid(next_rand_x, next_rand_y, next_rand_z, length):
                next_p = Point_d(3, [next_rand_x, next_rand_y, next_rand_z])
                G.add_node(next_p)
                points.append(next_p)
                i += 1
                if i % 500 == 0:
                    print(i, "landmarks sampled", file=writer)
    print(num_landmarks, "landmarks sampled", file=writer)
    # ==== MAIN AREA OF OUR CODE - PRM_GAUSSIAN ====

    # ==== MAIN AREA OF OUR CODE - DISTANCE 1 ====
    # distance used for nearest neighbor search
    def custom_dist(p, q):
        base_rod_position = [p[0], p[1], p[0] + length.to_double() * math.cos(p[2]), p[1] + length.to_double() * math.sin(p[2])]
        target_rod_position = [q[0], q[1], q[0] + length.to_double() * math.cos(q[2]), q[1] + length.to_double() * math.sin(q[2])]

        sd = math.sqrt((base_rod_position[0]-target_rod_position[0])**2 +
                       (base_rod_position[1] - target_rod_position[1])**2 +
                       (base_rod_position[2] - target_rod_position[2])**2 +
                       (base_rod_position[3] - target_rod_position[3])**2)

        return sd
    
    # distance used to weigh the edges
    def edge_weight(p, q):
        base_rod_position = [p[0], p[1], p[0] + length.to_double() * math.cos(p[2]), p[1] + length.to_double() * math.sin(p[2])]
        target_rod_position = [q[0], q[1], q[0] + length.to_double() * math.cos(q[2]), q[1] + length.to_double() * math.sin(q[2])]

        sd = math.sqrt((base_rod_position[0]-target_rod_position[0])**2 +
                       (base_rod_position[1] - target_rod_position[1])**2 +
                       (base_rod_position[2] - target_rod_position[2])**2 +
                       (base_rod_position[3] - target_rod_position[3])**2)

        return sd
    # ==== MAIN AREA OF OUR CODE - DISTANCE 1 ====

    # sklearn (which we use for nearest neighbor search) works with numpy array
    # of points represented as numpy arrays
    _points = np.array([point_d_to_arr(p) for p in points])

    # User defined metric cannot be used with the kd_tree algorithm
    _K = min(num_landmarks, K)
    nearest_neighbors = sklearn.neighbors.NearestNeighbors(n_neighbors=_K, metric=custom_dist, algorithm='auto')
    # nearest_neighbors = sklearn.neighbors.NearestNeighbors(n_neighbors=K, algorithm='kd_tree')
    nearest_neighbors.fit(_points)
    # Try to connect neighbors
    print('Connecting landmarks', file=writer)
    for i in range(len(points)):
        if not isRunning[0]:
            print("Aborted", file=writer)
            return path, G

        p = points[i]
        # Obtain the K nearest neighbors
        k_neighbors = nearest_neighbors.kneighbors([_points[i]], return_distance=False)

        for j in k_neighbors[0]:
            neighbor = points[j]
            for clockwise in (True, False):
                # check if we can add an edge to the graph
                if cd.is_rod_motion_valid(p, neighbor, clockwise, length):
                    weight = edge_weight(point_d_to_arr(p), point_d_to_arr(neighbor))
                    G.add_edge(p, neighbor, weight=weight, clockwise=clockwise)
                    break
        if i % 100 == 0:
            print('Connected', i, 'landmarks to their nearest neighbors', file=writer)
        i += 1

    if nx.has_path(G, begin, end):
        shortest_path = nx.shortest_path(G, begin, end)
        print("path found", file=writer)
        print("distance:", nx.shortest_path_length(G, begin, end, weight='weight'), file=writer)

        if len(shortest_path) == 0:
            return path
        first = shortest_path[0]
        path.append((first[0], first[1], first[2], True))
        for i in range(1, len(shortest_path)):
            last = shortest_path[i-1]
            next = shortest_path[i]
            # determine correct direction
            clockwise = G.get_edge_data(last, next)["clockwise"]
            path.append((next[0], next[1], next[2], clockwise))
    else:
        print("no path was found", file=writer)
    t1 = time.perf_counter()
    print("Time taken:", t1 - t0, "seconds", file=writer)
    return path
