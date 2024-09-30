# Import required packages for robot control and communication
import argparse
import time
import random
import zmq
from thymiodirect import Connection, Thymio

def detect_obstacle(prox_values, threshold=1000):
    """
    Check if there is an obstacle based on proximity sensor values.

    Args:
    - prox_values (list): List of proximity sensor values.
    - threshold (int): Threshold value to determine if an obstacle is detected.

    Returns:
    - bool: True if an obstacle is detected, otherwise False.
    """
    # Iterate through proximity sensor values and check if any exceed the threshold
    for value in prox_values:
        if value > threshold:
            return True  # Obstacle detected
    return False  # No obstacle detected

def detect_line(prox_values, threshold=300):
    """
    Detect if there is a line under the robot based on ground sensor values.

    Args:
    - prox_values (list): List of ground sensor values.
    - threshold (int): Threshold value to detect a line.

    Returns:
    - int: 1 if a line is detected on the left, 2 if on the right, 0 if none.
    """
    # Check left and right ground sensor values to detect a line
    if prox_values[0] < threshold:
        return 1  # Line detected on the left side
    elif prox_values[1] < threshold:
        return 2  # Line detected on the right side
    return 0  # No line detected

def main(robot_id='0', ip='localhost', port=5556):
    """
    Main loop of the program to control a Thymio robot.

    Args:
    - robot_id (str): ID of the robot for ZMQ communication.
    - ip (str): IP address for the ZMQ socket.
    - port (int): Port number for the ZMQ socket.
    """
    try:
        # Initialize and connect to the Thymio robot
        thymio_handler = Thymio(
            serial_port=Connection.serial_default_port(),  # Automatically detect serial port
            on_connect=lambda node_id: print(f'Thymio {node_id} is connected')  # Notify on connection
        )
        thymio_handler.connect()  # Establish connection to the robot
        robot = thymio_handler.first_node()  # Get the first connected Thymio robot

        # Create a ZMQ context and subscriber socket for communication
        context = zmq.Context()  # Create a ZMQ context for messaging
        zmq_socket = context.socket(zmq.SUB)  # Create a subscriber socket
        zmq_socket.connect(f'tcp://{ip}:{port}')  # Connect to the specified IP and port
        
        # Subscribe to specific topics for receiving messages
        zmq_socket.setsockopt_string(zmq.SUBSCRIBE, 'all')  # Subscribe to messages for all robots
        zmq_socket.setsockopt_string(zmq.SUBSCRIBE, robot_id)  # Subscribe to messages for this specific robot

        # Robot configuration and control variables
        robot_speed = 250             # Maximum speed of the robot in units
        action_start_time = 0         # Time when the current action started
        action_duration = 0           # Duration for which the current action will run
        back_duration = 1             # Fixed duration for the 'back' action
        rotation_direction = 0        # Direction of rotation (1 for left, -1 for right)

        robot_action = 'stop'         # Initial action state of the robot
        robot_state = 'off'           # Initial state of the robot (off)

        while True:
            # Receive and process data from the ZMQ socket
            try:
                topic, data = zmq_socket.recv(flags=zmq.NOBLOCK).decode('utf-8').split()
                
                # Process messages for different topics
                if topic == 'all':  # If message is for all robots
                    robot_state = data  # Update robot state based on received data
                elif topic == robot_id:  # If message is for this specific robot
                    robot_action = data  # Update action based on received message
                    print(f'Action: {robot_action}, ID: {robot_id}')  # Debugging output

            except zmq.Again:
                # No message available; continue to the next loop iteration
                pass

            # Handle the robot's state and determine actions
            if robot_state == 'off':
                robot_action = 'stop'  # If robot is off, it should stop
            elif robot_state == 'on':
                if robot_action == 'stop':
                    robot_action = 'go'  # If stopped, switch to 'go'
                elif robot_action == 'pause':
                    action_duration = 0  # Reset any ongoing action duration if paused
                elif robot_action == 'go':
                    # Check for obstacles and lines to react accordingly
                    if detect_obstacle(robot['prox.horizontal'][:5]):
                        robot_action = 'avoid'  # Switch to avoidance if an obstacle is detected
                        action_duration = random.uniform(0.5, 1.5)  # Random duration for avoidance
                        rotation_direction = random.choice([-1, 1])  # Randomize rotation direction
                        action_start_time = time.time()  # Record start time for the action
                    # Check for line detection
                    line_detection = detect_line(robot['prox.ground.reflected'])
                    if line_detection == 1:
                        robot_action = 'back'  # Line detected on the left, move back
                        action_duration = back_duration
                        rotation_direction = 1  # Rotate left while backing up
                        action_start_time = time.time()
                    elif line_detection == 2:
                        robot_action = 'back'  # Line detected on the right, move back
                        action_duration = back_duration
                        rotation_direction = -1  # Rotate right while backing up
                        action_start_time = time.time()
                elif robot_action == 'back':
                    # Check for obstacles while backing up
                    if detect_obstacle(robot['prox.horizontal'][-2:]):
                        robot_action = 'avoid'  # Switch to avoidance if an obstacle is detected
                        action_duration = random.uniform(0.5, 1.5)  # Random duration for avoidance
                        rotation_direction = random.choice([-1, 1])
                        action_start_time = time.time()

                # Check if the current action's time limit has been exceeded
                if action_duration > 0 and time.time() - action_start_time > action_duration:
                    if robot_action == 'back':
                        # Back action completed, switch to avoidance
                        robot_action = 'avoid'
                        action_duration = random.uniform(0.5, 1.5)  # Randomize avoidance duration
                        action_start_time = time.time()
                    else:
                        # Avoidance or pause completed, resume normal operation
                        robot_action = 'go'
                        action_duration = 0

            # Execute the robot's current action based on the state
            if robot_action == 'go':
                # Move forward at set speed
                robot['motor.left.target'] = robot_speed
                robot['motor.right.target'] = robot_speed
            elif robot_action == 'avoid':
                # Rotate in the opposite direction to avoid obstacle
                robot['motor.left.target'] = rotation_direction * robot_speed
                robot['motor.right.target'] = -rotation_direction * robot_speed
            elif robot_action == 'back':
                # Move backward at set speed
                robot['motor.left.target'] = -robot_speed
                robot['motor.right.target'] = -robot_speed
            elif robot_action in ('stop', 'pause'):
                # Stop all motors when stopping or pausing
                robot['motor.left.target'] = 0
                robot['motor.right.target'] = 0

    except Exception as error:
        # Handle unexpected errors by stopping the robot
        robot['motor.left.target'] = 0
        robot['motor.right.target'] = 0
        print(f'Error: {error}')  # Print the error message for debugging
    except KeyboardInterrupt:
        # Handle keyboard interruption (Ctrl+C) by stopping the robot
        robot['motor.left.target'] = 0
        robot['motor.right.target'] = 0
        print('Keyboard Interrupt')  # Inform user about the interruption

if __name__ == '__main__':
    # Parse command-line arguments to configure the robot's connection
    parser = argparse.ArgumentParser(description='Configure optional arguments to run the code with a Thymio robot.')
    
    # Define command-line arguments for robot ID, IP, and port
    parser.add_argument('-d', '--id', help='Set the robot ID for ZMQ communication (default: 0)', default='0')
    parser.add_argument('-i', '--ip', help='Set the TCP host IP for ZMQ communication (default: localhost)', default='localhost')
    parser.add_argument('-p', '--port', help='Set the TCP port for ZMQ communication (default: 5556)', default=5556, type=int)

    # Parse arguments and pass them to the main function
    args = parser.parse_args()
    main(robot_id=args.id, ip=args.ip, port=args.port)  # Start the main control loop with parsed arguments
