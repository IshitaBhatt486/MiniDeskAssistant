from gpiozero import Motor, DistanceSensor, DigitalInputDevice
from time import sleep, monotonic

# ---------------- MOTOR CONNECTIONS ----------------

left_motor = Motor(
    forward=22,
    backward=23,
    enable=13
)

right_motor = Motor(
    forward=27,
    backward=17,
    enable=12
)

# ---------------- ULTRASONIC SENSOR ----------------

sensor = DistanceSensor(
    echo=25,
    trigger=24,
    max_distance=2.0,
    threshold_distance=0.20,
    queue_len=1
)

STOP_DISTANCE = 0.20  # 20 cm

# ---------------- IR EDGE SENSORS ----------------

front_ir = DigitalInputDevice(19)
back_ir = DigitalInputDevice(26)

# LOW = floor detected
# HIGH = no floor detected
FLOOR_VALUE = 0

# ---------------- SETTINGS ----------------

SPEED = 0.5
CHECK_INTERVAL = 0.02


# ---------------- MOVEMENT FUNCTIONS ----------------

def stop():
    left_motor.stop()
    right_motor.stop()


def forward():
    left_motor.forward(SPEED)
    right_motor.forward(SPEED)


def backward():
    left_motor.backward(SPEED)
    right_motor.backward(SPEED)


def turn_left():
    left_motor.backward(SPEED)
    right_motor.forward(SPEED)


def turn_right():
    left_motor.forward(SPEED)
    right_motor.backward(SPEED)


# ---------------- SAFETY CHECKS ----------------

def floor_detected(ir_sensor):
    return ir_sensor.value == FLOOR_VALUE


def check_safety(direction):

    front_safe = floor_detected(front_ir)
    back_safe = floor_detected(back_ir)

    # Forward movement: check front IR
    if direction == "forward" and not front_safe:
        print("FRONT EDGE DETECTED! STOPPING.")
        return False

    # Backward movement: check rear IR
    if direction == "backward" and not back_safe:
        print("BACK EDGE DETECTED! STOPPING.")
        return False

    # Turning: require both sensors to see the floor
    if direction in ("left", "right"):
        if not front_safe or not back_safe:
            print("EDGE DETECTED! STOPPING TURN.")
            return False

    # Ultrasonic obstacle detection during forward movement
    if direction == "forward":
        distance = sensor.distance

        if distance <= STOP_DISTANCE:
            print(
                f"OBSTACLE DETECTED: {distance * 100:.1f} cm"
            )
            return False

    return True


# ---------------- EXECUTE MOVEMENT ----------------

def execute_movement(direction, duration):

    movement_functions = {
        "forward": forward,
        "backward": backward,
        "left": turn_left,
        "right": turn_right
    }

    print(f"\nMoving {direction.upper()} for {duration} seconds")

    end_time = monotonic() + duration

    try:
        while monotonic() < end_time:

            # Check safety before applying motor power
            if not check_safety(direction):
                stop()
                return

            movement_functions[direction]()

            sleep(CHECK_INTERVAL)

        print("Movement completed.")

    finally:
        stop()


# ---------------- MAIN MENU ----------------

try:

    print("\n==============================")
    print("       ROBOT CONTROL")
    print("==============================")

    while True:

        print("\nSelect Movement:")
        print("1. Forward")
        print("2. Backward")
        print("3. Left")
        print("4. Right")
        print("0. Exit")

        choice = input("\nEnter your choice: ").strip()

        directions = {
            "1": "forward",
            "2": "backward",
            "3": "left",
            "4": "right"
        }

        if choice == "0":
            print("Exiting robot control.")
            break

        if choice not in directions:
            print("Invalid option. Try again.")
            continue

        try:
            duration = float(
                input("Enter movement duration (seconds): ")
            )

            if duration <= 0:
                print("Duration must be greater than zero.")
                continue

        except ValueError:
            print("Please enter a valid number.")
            continue

        execute_movement(directions[choice], duration)

except KeyboardInterrupt:
    print("\nEmergency stop requested.")

finally:
    stop()

    sensor.close()
    front_ir.close()
    back_ir.close()

    left_motor.close()
    right_motor.close()

    print("All motors stopped. Robot closed.")
