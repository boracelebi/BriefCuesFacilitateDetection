import zmq
import time
import random
import sys
from TactileComms import TactileComm
from pylsl import StreamInfo, StreamOutlet, IRREGULAR_RATE
from pygame import mixer
import RPi.GPIO as GPIO

# Setup ZMQ socket
context = zmq.Context()
publisher_socket = context.socket(zmq.PUB)
publisher_socket.bind("tcp://*:5556")

# Inititialize the LSL streams
state_streams = {
    'robot_state':      StreamOutlet(StreamInfo('Robot_state',      'state', 1, IRREGULAR_RATE, 'int8', 'robot_state')),
    'robot_id':         StreamOutlet(StreamInfo('Robot_id',         'state', 1, IRREGULAR_RATE, 'int8', 'robot_id')),
    'cue_state':        StreamOutlet(StreamInfo('Cue_state',        'state', 1, IRREGULAR_RATE, 'int8', 'cue_state')),
    'stop_state':       StreamOutlet(StreamInfo('Stop_state',       'state', 1, IRREGULAR_RATE, 'int8', 'stop_state')),
    'user_input':       StreamOutlet(StreamInfo('User_input',       'state', 1, IRREGULAR_RATE, 'int8', 'user_input')),
}

# Initialize the haptic vest communication
haptic_vest = TactileComm(comport='/dev/ttyACM0', baudrate=115200)
vibration_intensity = 40

# Initialize the audio mixer
mixer.init(buffer=4096)

# Initialize the GPIO pins
buttons = {
    'experiment': 12,
    'training': 19,
    'audio': 16,
    'tactile': 6,
    'multi': 20,
    'start': 21,
    'stop': 13,
    'user_main': 18,
    'user_short': 17,
    'user_long': 4
}

GPIO.setmode(GPIO.BCM)
for button_pin in buttons.values():
    GPIO.setup(button_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


# Global experiment parameters
experiment_params = {
    'num_robots': 10,
    'robot_state': -1,
    'cue_state': -1,
    'stop_state': -1,
    'stop_duration': 5,
    'robot_stop_id': -1,
    'start_offset': 30,
    'end_offset': 30,
    'stop_offset': 0.02,
    'min_interval': 8,
    'max_interval': 12
}

DEBUG = True


def generate_trials(num_repeats=0, duration=0, start_offset=30, end_offset=10, cue_types=[0, 1, 2, 3], effect_types=[0, 1, 2, 3, 4, 5, 6], min_interval=8, max_interval=12):
    """
    Generate trials for the experiment based on the specified parameters.

    Args:
        num_repeats (int): Number of repetitions for each combination of cues and effects.
        duration (int): Duration of the entire experiment in seconds.
        start_offset (int): Time offset at the start of the experiment in seconds.
        end_offset (int): Time offset at the end of the experiment in seconds.
        cue_types (list): List of cue types to be used in the trials.
        effect_types (list): List of effect types to be used in the trials.
        min_interval (int): Minimum interval between trials in seconds.
        max_interval (int): Maximum interval between trials in seconds.

    Returns:
        list: List of tuples representing the trials with each tuple containing
              (timestamp, cue, effect).
    """
    trials = []  # Initialize an empty list to hold the generated trials

    if num_repeats:
        # Generate all combinations of cues and effects
        combinations = [(cue, effect) for cue in cue_types for effect in effect_types]
        repeated_combinations = combinations * num_repeats  # Repeat each combination num_rep times
        random.shuffle(repeated_combinations)  # Shuffle the combinations for randomness

        timestamp = start_offset  # Start timestamp for the first trial
        for cue, effect in repeated_combinations:
            trials.append((timestamp, cue, effect))  # Append the trial with its timestamp
            timestamp += random.randint(min_interval, max_interval)  # Update the timestamp for the next trial

    else:
        # If no repetitions are specified, calculate the number of trials based on duration
        num_repeats = int((duration - start_offset - end_offset) / ((max_interval + min_interval) / 2))
        timestamp = start_offset  # Start timestamp for the first trial
        for _ in range(num_repeats):
            trials.append((timestamp, cue_types[0], 1))  # Default to the first cue type
            timestamp += random.randint(min_interval, max_interval)  # Update the timestamp for the next trial

    return trials

def handle_trial(trial, stop_robot=False):
    """
    Handle a single trial by setting the cue and stop states based on the trial configuration.

    Args:
        trial (tuple): A tuple containing (timestamp, cue, effect) for the trial.

    Returns:
        None
    """
    global experiment_params
    experiment_params['stop_state'] = trial[2] + 1
    stop_duration = 0.2 + 0.1 * trial[2]  # Calculate stop duration based on effect

    cue = trial[1]
    if cue == 0:
        print(f"\n\nNo Cue, Stop duration: {stop_duration:.1f}s")
        experiment_params['cue_state'] = 1
    elif cue == 1:
        print(f"\n\nAudio Cue, Stop duration: {stop_duration:.1f}s")
        mixer.Channel(1).play(mixer.Sound('sine.wav'))
        experiment_params['cue_state'] = 2
    elif cue == 2:
        print(f"\n\nTactile Cue, Stop duration: {stop_duration:.1f}s")
        for dot in [1, 4, 13, 16, 17, 20, 29, 32]:
            haptic_vest.submit_dot(dot, 10, vibration_intensity)
        experiment_params['cue_state'] = 3
    elif cue == 3:
        print(f"\n\nAudio and Tactile Cue, Stop duration: {stop_duration:.1f}s")
        mixer.Channel(1).play(mixer.Sound('sine.wav'))
        for dot in [1, 4, 13, 16, 17, 20, 29, 32]:
            haptic_vest.submit_dot(dot, 10, vibration_intensity)
        experiment_params['cue_state'] = 4

    # Stop the robot if required
    if stop_robot:
        if experiment_params['robot_stop_id'] == -1:
            experiment_params['robot_stop_id'] = random.randint(0, experiment_params['num_robots'] - 1)
        
        publisher_socket.send_string(f"{experiment_params['robot_stop_id']} pause")
        state_streams['robot_id'].push_sample([experiment_params['robot_stop_id'] + 1])
        print(f"Stop Robot: {experiment_params['robot_stop_id']}")
        experiment_params['robot_state'] = 1

def end_pause():
    """
    End the current pause and reset the states to default.

    Args:
        None

    Returns:
        None
    """
    global experiment_params
    if experiment_params['robot_stop_id'] != -1:
        publisher_socket.send_string(f"{experiment_params['robot_stop_id']} go")
        print(f"\nResume Robot: {experiment_params['robot_stop_id']}")
    
    experiment_params['robot_state'] = 0
    experiment_params['cue_state'] = 0
    experiment_params['stop_state'] = 0

def push_lsl_streams():
    """
    Push the current state of the experiment to the LSL streams.

    Args:
        None

    Returns:
        None
    """
    global state_streams, experiment_params
    state_streams['cue_state'].push_sample([experiment_params['cue_state']])
    state_streams['robot_state'].push_sample([experiment_params['robot_state']])
    state_streams['stop_state'].push_sample([experiment_params['stop_state']])

    user_input = 0
    if GPIO.input(buttons['user_main']): user_input |= (1 << 0)
    if GPIO.input(buttons['user_short']): user_input |= (1 << 1)
    if GPIO.input(buttons['user_long']): user_input |= (1 << 2)
    
    state_streams['user_input'].push_sample([user_input])
        
def reset_robots():
    """
    Reset the state of all robots, stopping their operations.

    Args:
        None

    Returns:
        None
    """
    publisher_socket.send_string("all off")
    time.sleep(0.5)
    publisher_socket.send_string("led 0")



def run_training(is_training=False, is_test=False, num_repeats=0, cue_types=[0], effect_types=[0, 1, 2, 3, 4, 5, 6]):
    """
    Run the main experiment logic including cue presentation and robot stopping.

    Args:
        is_training (bool): If True, the experiment runs in training mode.
        is_test (bool): If True, the experiment runs in test mode.
        num_repeats (int): Number of trial repetitions.
        cue_types (list): List of cue types for trials.
        effect_types (list): List of effect types for trials.

    Returns:
        None
    """
    global experiment_params

    # generate the training trials
    trials = generate_trials(num_repeats=num_repeats, cue_types=cue_types, effect_types=effect_types)
    print(f"\nTrials: {trials}")

    # get the duration of the training and add 10 seconds for the end offset
    total_duration = trials[-1][0] + 10

    # reset the robots
    reset_robots()

    # start the white noise
    mixer.Channel(0).play(mixer.Sound('whitenoise.wav'), -1)

    # reset the state variables 
    experiment_params['cue_state'] = 0
    experiment_params['robot_state'] = 0


    # initianilze the experiment parameters
    trial_index = 0
    robot_stopped = False
    robot_detected = False
    trial_finished = False
    in_trial = False

    # initialize print helpers
    last_print_time = 0

    # initialize the experiment clock
    start_time = time.time()
    elapsed_time = 0
    robot_stop_time = 0
    lsl_update_time = 0

    # select a random robot for the training and start it
    if is_training or is_test:
        experiment_params['robot_stop_id'] = random.randint(0, experiment_params['num_robots']-1)     
        publisher_socket.send_string("%s on" % str(experiment_params['robot_stop_id']))
    else:
        experiment_params['robot_stop_id'] = -1
        publisher_socket.send_string("all on")

    if is_training:
        print('Training started.\n')
    elif is_test:
        print('Test started.\n')
    else:
        print('Experiment started.\n')

    # Main training loop
    while elapsed_time <= total_duration:

        # Upddate the elapsed time
        if not in_trial:
            elapsed_time = (time.time() - start_time)

        # Print the experiment state and time 1 time per second
        if time.time() - last_print_time > 1:
            last_print_time = time.time()
            
            # Clear the line
            sys.stdout.write("\033[K")
            if robot_stopped:  
                print("\rWaiting for detection. Elapsed: ", int(time.time()-robot_stop_time),"\t", end="")
            elif robot_detected:
                print("\rResponse Window. Elapsed: ", int(time.time()-robot_stop_time),"\t", end="")
            else:
                print("\rElapsed ", int(elapsed_time),"\t", end="")

        # Check if the current trial is up and handle it
        if trial_index < len(trials) and not robot_stopped and elapsed_time >= trials[trial_index][0] and not in_trial:
            handle_trial(trials[trial_index], stop_robot=True)
            robot_stopped = True
            robot_stop_time = time.time()
            in_trial = True

        # Check if the stopped robot has been detected 
        if trial_index < len(trials) and robot_stopped and GPIO.input(buttons['user_main']):
            
            if is_training:
                # Give the user feedback on the bisected period
                if trials[trial_index][2] == 0: mixer.Channel(1).play(mixer.Sound('Short.wav'))
                elif trials[trial_index][2] == 6: mixer.Channel(1).play(mixer.Sound('Long.wav'))

                # No response needed in training
                trial_finished = True
            
            else:
                robot_detected = True


            # Add the temporal bisection period and restart the robot
            time.sleep(0.2 + 0.1 * trials[trial_index][2])
            
            # Restart the robot
            end_pause()

            # Reset to select new random robot next time
            if not is_test and not is_training:
                experiment_params['robot_stop_id'] = -1

            # Turn on the led if it is not a training trial
            if not is_training:
                publisher_socket.send_string("led 1")  

            # MOve on to the response window
            robot_stopped = False

        # Wait for the user respnse
        if trial_index < len(trials) and robot_detected and (GPIO.input(buttons['user_long']) == 1 or GPIO.input(buttons['user_short']) == 1):
            print("\nUser input detected", GPIO.input(buttons['user_long']), GPIO.input(buttons['user_short']))
            
            # Provide feedback 
            if GPIO.input(buttons['user_long']) == 1: 
                if trials[trial_index][2]  == 0:
                    print("wrong, short and not long")
                    mixer.Channel(1).play(mixer.Sound('Wrong.wav'))
                    publisher_socket.send_string("led 3")  
                elif trials[trial_index][2]  == 6:
                    print("correct, long")
                    mixer.Channel(1).play(mixer.Sound('Correct.wav'))
                    publisher_socket.send_string("led 2")  

            # Provide feedback
            if GPIO.input(buttons['user_short']) == 1: 
                if trials[trial_index][2]  == 0:
                    print("correct, short ")
                    mixer.Channel(1).play(mixer.Sound('Correct.wav'))
                    publisher_socket.send_string("led 2")  
                elif trials[trial_index][2]  == 6:
                    print("wrong, long and not short")
                    mixer.Channel(1).play(mixer.Sound('Wrong.wav'))
                    publisher_socket.send_string("led 3")  

            # Move to the next trial
            robot_detected = False
            trial_finished = True
        
        # The trial is finished update the state variables and move on
        if trial_finished:
            # Reset the state variables
            trial_finished = False
            in_trial = False

            # Turn off the led
            publisher_socket.send_string("led 0")  

            # Move to the next trial
            trial_index += 1

            # Account for the time taken to respond
            start_time += time.time() - robot_stop_time

            # Add a blank line for better readability
            print('\n')

        # Update the LSL streams at 100 Hz
        if time.time() - lsl_update_time >= 0.01:
            push_lsl_streams()  
            lsl_update_time = time.time()

        # Check for preleminary experiment stop 
        if GPIO.input(buttons['stop']) != 1:
            break

    print('\nExperiment ended after %s seconds.\n' % str(elapsed_time))
    reset_robots()



def main():
    """
    Main function to start the experiment based on button inputs. It listens for specific button
    configurations and initiates the respective experiment sequence.

    Args:
        None

    Returns:
        None
    """
    try:
        lsl_update_time = 0
        while True:

            if time.time() - lsl_update_time >= 0.01:
                state_streams['cue_state'].push_sample([-1])
                state_streams['robot_state'].push_sample([-1])
                state_streams['stop_state'].push_sample([-1])
                state_streams['user_input'].push_sample([-1])
                lsl_update_time = time.time()

            mixer.Channel(0).pause()
            if GPIO.input(buttons['start']) != 1 and GPIO.input(buttons['training']) == 1:
                run_training(is_training=True, num_repeats=7, cue_types=[0], effect_types=[0, 6])
            elif GPIO.input(buttons['start']) != 1 and GPIO.input(buttons['audio']) == 1:
                run_training(is_test=True, num_repeats=7, cue_types=[0], effect_types=[0, 6])
            elif GPIO.input(buttons['start']) != 1 and GPIO.input(buttons['tactile']) == 1:
                run_training(num_repeats=13, cue_types=[0, 2])

            if GPIO.input(buttons['stop']) != 1:
                publisher_socket.send_string("all off")
                break

    except KeyboardInterrupt:
        publisher_socket.send_string("all off")
        publisher_socket.close()

if __name__ == '__main__':
    main()
    