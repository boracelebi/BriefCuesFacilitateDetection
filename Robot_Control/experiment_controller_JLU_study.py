import zmq
import time
import random
import sys
from TactileComms import TactileComm
from pylsl import StreamInfo, StreamOutlet, IRREGULAR_RATE
from pygame import mixer
import RPi.GPIO as GPIO

# Setup the ZeroMQ socket for communication between processes
zmq_socket = zmq.Context().socket(zmq.PUB)
zmq_socket.bind("tcp://*:5556")  # Bind the socket to all interfaces on port 5556

# Create LSL (Lab Streaming Layer) outlets for different data streams
robot_state_stream = StreamOutlet(StreamInfo('robot_state', 'state', 1, IRREGULAR_RATE, 'int8', 'rob_state'))
robot_id_stream = StreamOutlet(StreamInfo('robot_id', 'state', 1, IRREGULAR_RATE, 'int8', 'rob_id'))
cue_state_stream = StreamOutlet(StreamInfo('cue_state', 'state', 1, IRREGULAR_RATE, 'int8', 'cue_state'))
user_stream = StreamOutlet(StreamInfo('user_input', 'state', 1, IRREGULAR_RATE, 'int8', 'user_input'))

# Allow time for the socket to set up properly
time.sleep(3)

# Setup the haptic vest communication via serial port
haptic_vest = TactileComm(comport='/dev/ttyACM0', baudrate=115200)
vibration_intensity = 40  # Set the intensity level for haptic feedback

# Initialize the audio mixer with a specified buffer size
mixer.init(buffer=4096)

# Setup GPIO pins for buttons, using BCM pin numbering
buttons = {
    'experiment': 12,  # Button to select the experiment
    'tactile': 6,      # Button for tactile feedback trial
    'training': 19,    # Button for training mode
    'audio': 16,       # Button for audio feedback trial
    'multi': 20,       # Button for multisensory trial 
    'user': 18,        # Button for user input from main button
    'stop': 13,        # Button to stop the experiment - Normally open
    'start': 21,       # Button to start specific experiments - Normally open
}

# Initialize GPIO mode and setup input pins with pull-down resistors
GPIO.setmode(GPIO.BCM)
for button in buttons.values():
    GPIO.setup(button, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# Setup global experiment parameters
num_robots = 10  # Number of robots involved in the experiment
robot_state = -1  # Initial state of the robot (-1 indicates not started)
cue_state = -1  # Initial state of the cue (-1 indicates no cue emitted)
robot_stop_duration = 5  # Duration for which the robot should pause
robot_stop_id = 0  # Identifier for the robot that is paused
start_offset = 30  # Time before the first trial starts
end_offset = 30    # Time to wait after the last trial
stop_offset = 0.02  # Small pause before stopping the robot

# Random interval settings for trials
min_interval = 8  # Minimum time interval between trials
max_interval = 12  # Maximum time interval between trials

def generate_trials(num_rep=0, duration=0, start_offset=30, min_end_offset=10, cue_types=[0, 1, 2, 3], effect_types=[0, 1]):
    """
    Generate a list of trials based on specified parameters.

    Args:
        num_rep (int): Number of repetitions for each cue-effect combination.
        duration (float): Total duration of the experiment.
        start_offset (float): Initial delay before starting trials.
        min_end_offset (float): Minimum time to keep at the end of the experiment.
        cue_types (list): List of available cue types (e.g., audio, tactile).
        effect_types (list): List of effect types (e.g., on/off).

    Returns:
        list: List of generated trials with timestamps and cue/effect pairs.
    """
    trials = []  # Initialize an empty list to hold the generated trials

    if num_rep:
        # Generate all combinations of cues and effects
        combinations = [(cue, effect) for cue in cue_types for effect in effect_types]
        repeated_combinations = combinations * num_rep  # Repeat each combination num_rep times
        random.shuffle(repeated_combinations)  # Shuffle the combinations for randomness

        timestamp = start_offset  # Start timestamp for the first trial
        for cue, effect in repeated_combinations:
            trials.append((timestamp, cue, effect))  # Append the trial with its timestamp
            inter_trial_interval = random.randint(min_interval, max_interval)  # Random interval
            timestamp += inter_trial_interval  # Update the timestamp for the next trial

    else:
        # If no repetitions are specified, calculate the number of trials based on duration
        num_rep = int((duration - start_offset - min_end_offset) / ((max_interval + min_interval) / 2))
        timestamp = start_offset  # Start timestamp for the first trial
        for _ in range(num_rep):
            trials.append((timestamp, cue_types[0], 1))  # Default to the first cue type
            inter_trial_interval = random.randint(min_interval, max_interval)  # Random interval
            timestamp += inter_trial_interval  # Update the timestamp for the next trial

    return trials  # Return the list of generated trials

def emit_cue(trial):
    """
    Emit the specified cue based on the trial data.

    Args:
        trial (tuple): The trial data containing timestamp, cue type, and effect type.
    """
    global cue_state  # Use the global cue_state variable

    # Emit the cue based on its type
    if trial[1] == 0:
        print("Cue 1 - None")  # No cue
        cue_state = 1  # Update the cue state
    elif trial[1] == 1:
        print("Cue 2 - Audio")  # Audio cue
        mixer.Channel(1).play(mixer.Sound('sine.wav'))  # Play audio
        cue_state = 2  # Update the cue state
    elif trial[1] == 2:
        print("Cue 3 - Tactile")  # Tactile cue
        # Emit haptic feedback through the vest on specified dots
        for dot in [1, 4, 13, 16, 17, 20, 29, 32]:
            haptic_vest.submit_dot(dot, 10, vibration_intensity)
        cue_state = 3  # Update the cue state
    elif trial[1] == 3:
        print("Cue 4 - AudioTactile")  # Combined audio and tactile cue
        mixer.Channel(1).play(mixer.Sound('sine.wav'))  # Play audio
        for dot in [1, 4, 13, 16, 17, 20, 29, 32]:
            haptic_vest.submit_dot(dot, 10, vibration_intensity)  # Emit haptic feedback
        cue_state = 4  # Update the cue state

def start_pause(trial):
    """
    Start a pause for the robot based on the trial data.

    Args:
        trial (tuple): The trial data containing timestamp, cue type, and effect type.
    """
    global robot_state, robot_stop_id  # Use global variables for robot state and stop ID

    if trial[2] == 1:  # Check if the effect type requires a pause
        robot_stop_id = random.randint(0, num_robots - 1)  # Randomly select a robot to pause
        zmq_socket.send_string(f"{robot_stop_id} pause")  # Send pause command to the robot
        robot_id_stream.push_sample([robot_stop_id + 1])  # Push the robot ID to the LSL stream
        print(f"{robot_stop_id} pause")  # Log the pause action
        robot_state = 1  # Update robot state to paused
    else:
        robot_stop_id = -1  # Reset stop ID if no pause is required
        robot_state = 2  # Set robot state to running

def end_pause():
    """
    End the pause for the robot, allowing it to resume operation.
    """
    global robot_state, cue_state, robot_stop_id  # Use global variables

    if robot_stop_id != -1:  # If a robot is currently paused
        zmq_socket.send_string(f"{robot_stop_id} go")  # Send go command to resume
        print(f"{robot_stop_id} go")  # Log the resume action

    robot_state = 0  # Reset the robot state to idle
    cue_state = 0  # Reset the cue state

def run_experiment(num_rep=0, duration=0, cue=0):
    """
    Run the experiment based on specified parameters.

    Args:
        num_rep (int): Number of repetitions for each trial.
        duration (float): Duration of the experiment in seconds.
        cue (int): Cue type to be used in the experiment.
    """
    global cue_state, robot_state  # Use global variables for state tracking

    # Generate the list of trials based on parameters
    trials = generate_trials(num_rep=num_rep, duration=duration, start_offset=start_offset, cue_types=cue)

    # Calculate the total experiment duration
    if num_rep:
        experiment_duration = trials[-1][0] + end_offset  # Last trial time plus end offset
    else:
        experiment_duration = duration  # Use the provided duration

    # Start playing white noise as background sound
    mixer.Channel(0).play(mixer.Sound('whitenoise.wav'), -1)

    # Initialize timing variables for the experiment
    experiment_start_time = time.time()  # Record the start time
    elapsed_time = 0  # Elapsed time since the start
    elapsed_time_last = 0  # Last recorded elapsed time
    trial_index = 0  # Current trial index
    cue_emitted = False  # Flag to track if a cue has been emitted
    robot_state = 0  # Initialize robot state to idle
    cue_state = 0  # Initialize cue state to no cue emitted

    last_lsl_time = 0  # Timing for LSL data push

    # Start all robots by sending "on" command
    zmq_socket.send_string("all on")

    if num_rep:
        print('Started pip & pop', trials)  # Log if repetitions are specified
    else:
        print('Started Cue experiment', trials)  # Log if running a cue experiment

    # Main experiment loop
    while (time.time() - experiment_start_time) <= experiment_duration: 
        # Push LSL data every 10 milliseconds
        if time.time() - last_lsl_time >= 0.01:
            robot_state_stream.push_sample([robot_state])  # Push current robot state
            cue_state_stream.push_sample([cue_state])  # Push current cue state
            user_stream.push_sample([GPIO.input(buttons['user'])])  # Push user input state
            last_lsl_time = time.time()  # Update last LSL push time

        # Calculate elapsed time since the start of the experiment
        elapsed_time = time.time() - experiment_start_time

        # Print the current elapsed time every second
        if elapsed_time - elapsed_time_last > 1:
            elapsed_time_last = elapsed_time
            sys.stdout.write("\033[K")  # Clear the current line in the console
            print("\r", int(elapsed_time), "\t", end="")  # Print the elapsed time

        # Check if the experiment should be stopped
        if GPIO.input(buttons['stop']) != 1:
            print(f'Experiment stopped after {elapsed_time} seconds.')  # Log stop time
            zmq_socket.send_string("all off")  # Stop all robots
            return  # Exit the function

        # Check if it's time to emit a cue
        if trial_index < len(trials) and not cue_emitted and elapsed_time >= trials[trial_index][0]:
            emit_cue(trials[trial_index])  # Emit the cue for the current trial
            cue_emitted = True  # Set the cue emitted flag

        # Pause the robot if it's time based on the trial data
        elif trial_index < len(trials) and (elapsed_time) >= trials[trial_index][0] + stop_offset and not robot_state:
            start_pause(trials[trial_index])  # Start the pause for the robot

        # Resume the robot after the pause duration
        elif trial_index < len(trials) and (elapsed_time) >= trials[trial_index][0] + stop_offset + robot_stop_duration:
            end_pause()  # End the pause for the robot
            trial_index += 1  # Increment to the next trial
            cue_emitted = False  # Reset cue emitted flag for the next trial

    print(f'Experiment ended after {elapsed_time} seconds.')  # Log the end time
    zmq_socket.send_string("all off")  # Stop all robots

def main():
    """
    Main function to continuously check button inputs and run experiments as needed.
    """
    try:
        last_lsl_time = 0  # Initialize last LSL push time
        while True:
            # Push LSL data every 10 milliseconds
            if time.time() - last_lsl_time >= 0.01:
                robot_state_stream.push_sample([-1])  # Push a default state for robots
                cue_state_stream.push_sample([-1])  # Push a default state for cues
                user_stream.push_sample([GPIO.input(buttons['user'])])  # Push user input state
                last_lsl_time = time.time()  # Update last LSL push time

            # Pause the white noise if the experiment button is pressed
            mixer.Channel(0).pause()
            if GPIO.input(buttons['experiment']) == 1:
                # Check button inputs to determine which experiment to start
                if GPIO.input(buttons['start']) != 1 and GPIO.input(buttons['training']) == 1:
                    run_experiment(num_rep=2, cue=[0, 1, 2, 3])  # Start training experiment
                elif GPIO.input(buttons['start']) != 1 and GPIO.input(buttons['audio']) == 1:
                    run_experiment(num_rep=10, cue=[0, 1, 2, 3])  # Start audio experiment
            else:
                # Check for other button presses to start different types of experiments
                if GPIO.input(buttons['start']) != 1 and GPIO.input(buttons['multi']) == 1:
                    run_experiment(duration=180, cue=[3])  # Multi-cue experiment
                elif GPIO.input(buttons['start']) != 1 and GPIO.input(buttons['tactile']) == 1:
                    run_experiment(duration=180, cue=[2])  # Tactile feedback experiment
                elif GPIO.input(buttons['start']) != 1 and GPIO.input(buttons['audio']) == 1:
                    run_experiment(duration=180, cue=[1])  # Audio feedback experiment
                elif GPIO.input(buttons['start']) != 1 and GPIO.input(buttons['none']) == 1:
                    run_experiment(duration=180, cue=[0])  # No cue experiment

            # Check if the stop button is pressed to stop all robots
            if GPIO.input(buttons['stop']) != 1:
                zmq_socket.send_string("all off")  # Stop all robots

    except KeyboardInterrupt:
        zmq_socket.send_string("all off")  # Stop all robots on interrupt
        zmq_socket.close()  # Close the ZeroMQ socket

if __name__ == '__main__':
    main()  # Start the main function
