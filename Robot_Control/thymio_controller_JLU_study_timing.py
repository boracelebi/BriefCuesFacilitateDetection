# Import required packages
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
    # Return True if any proximity value exceeds the threshold, indicating an obstacle
    return any(value > threshold for value in prox_values)

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
        # Initialize and connect to the robot using Thymio's direct connection
        thymio_handler = Thymio(
            serial_port=Connection.serial_default_port(),
            on_connect=lambda node_id: print(f'Thymio {node_id} is connected')
        )
        thymio_handler.connect()  # Establish connection to the robot
        robot = thymio_handler.first_node()  # Get the first connected Thymio robot

        # Create a ZMQ context and subscriber socket for communication
        context = zmq.Context()
        zmq_socket = context.socket(zmq.SUB)
        zmq_socket.connect(f'tcp://{ip}:{port}')  # Connect to the specified IP and port
        
        # Subscribe to specific topics for receiving messages
        zmq_socket.setsockopt_string(zmq.SUBSCRIBE, 'all')  # Subscribe to all robots
        zmq_socket.setsockopt_string(zmq.SUBSCRIBE, 'led')  # Subscribe to LED control messages
        zmq_socket.setsockopt_string(zmq.SUBSCRIBE, robot_id)  # Subscribe to messages for this specific robot

        # Robot configuration and control variables
        robot_speed = 250            # Maximum speed of the robot
        action_start_time = 0        # Timestamp for when the current action starts
        action_duration = 0          # Duration for which the current action will run
        back_duration = 1            # Fixed duration for the 'back' action
        rotation_direction = 0       # Direction of rotation (1 for left, -1 for right)

        robot_action = 'stop'        # Initial action state of the robot
        robot_state = 'off'          # Initial state of the robot (off)

        while True:
            # Receive and process data from the ZMQ socket
            try:
                topic, data = zmq_socket.recv(flags=zmq.NOBLOCK).decode('utf-8').split()
                
                # Process messages for different topics
                if topic == 'all':  # Message for all robots
                    robot_state = data
                elif topic == str(robot.id):  # Message for this specific robot
                    if data == 'on':
                        robot_state = 'on'  # Set robot state to on
                    else:
                        robot_action = data  # Update robot action based on received message
                    print(robot_action, robot.id)  # Debugging output
                elif topic == 'led':  # Handle LED control messages
                    if data == '1':
                        # Set LEDs to a bright white color
                        robot['leds.top'] = [32, 32, 32]
                        robot['leds.bottom.left'] = [32, 32, 32]
                        robot['leds.bottom.right'] = [32, 32, 32]
                        robot['leds.circle'] = [32, 32, 32, 32, 32, 32, 32, 32]
                    elif data == '2':
                        # Set LEDs to green
                        robot['leds.top'] = [0, 32, 0]
                        robot['leds.bottom.left'] = [0, 32, 0]
                        robot['leds.bottom.right'] = [0, 32, 0]
                    elif data == '3':
                        # Set LEDs to red
                        robot['leds.top'] = [32, 0, 0]
                        robot['leds.bottom.left'] = [32, 0, 0]
                        robot['leds.bottom.right'] = [32, 0, 0]
                    elif data == '4':
                        # Set LEDs to blue
                        robot['leds.top'] = [0, 0, 32]
                        robot['leds.bottom.left'] = [0, 0, 32]
                        robot['leds.bottom.right'] = [0, 0, 32]
                    else:
                        # Turn off all LEDs
                        robot['leds.top'] = [0, 0, 0]
                        robot['leds.bottom.left'] = [0, 0, 0]
                        robot['leds.bottom.right'] = [0, 0, 0]
                        robot['leds.circle'] = [0, 0, 0, 0, 0, 0, 0, 0]
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
                    action_duration = 0  # Stop any ongoing action
                elif robot_action == 'go':
                    # Check for obstacles and react accordingly
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
    
    parser.add_argument('-d', '--id', help='Set the robot ID for ZMQ communication (default: 0)', default='0')
    parser.add_argument('-i', '--ip', help='Set the TCP host IP for ZMQ communication (default: localhost)', default='localhost')
    parser.add_argument('-p', '--port', help='Set the TCP port for ZMQ communication (default: 5556)', default=5556, type=int)

    # Parse arguments and pass them to the main function
    args = parser.parse_args()
    main(robot_id=args.id, ip=args.ip, port=args.port)
