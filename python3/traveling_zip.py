#! /usr/bin/env python3

import os
from typing import Dict, List, TextIO
import math

# If you add or upgrade any pip packages, please specify in `requirements.txt`
import yaml  # noqa

# Each Nest has this many Zips
NUM_ZIPS = 10

# Each Zip can carry between 1 and this many packages per flight
# Note: a Zip can deliver more than 1 package per stop
MAX_PACKAGES_PER_ZIP = 3

# Zips fly a constant groundspeed (m/s)
ZIP_SPEED_MPS = 30

# Zips can fly a total roundtrip distance (m)
ZIP_MAX_CUMULATIVE_RANGE_M = 160 * 1000  # 160 km -> meters

# The two acceptable priorities
EMERGENCY = "Emergency"
RESUPPLY = "Resupply"

NEST = [0, 0]

# controls for order throttling to prioritize Emergency zips
MIN_RESUPPLY_ORDERS_NEEDED_TO_LOAD = 3
MIN_ZIPS_TO_SHIP_SINGLE_ORDERS = 8

# flight and order stats
EMERGENCY_ORDER_WAIT_TIME = []
RESUPPLY_ORDER_WAIT_TIME = []
ORDER_WAIT_TIME = []

FLIGHT_PLAN_ORDERS = []
FLIGHT_PLAN_DISTANCE = []

# assuming launch_flights is called once per minute
NUM_MINS_WITH_0_ZIPS_AVAILABLE = []
NUM_MINS_WITH_0_ZIPS_AVAILABLE_AND_EMERGENCY_ORDER = []


# You shouldn't need to modify this class
class Hospital:
    def __init__(self, name: str, north_m: int, east_m: int):
        self.name = name
        self.north_m = north_m
        self.east_m = east_m

    @staticmethod
    def load_from_csv(f: TextIO) -> Dict[str, "Hospital"]:
        """Reads and processes a CSV file object that conforms to the
        hospital.csv schema defined in README.md.

        Args:
            f (file_object): CSV file object to read into a dict.

        Returns:
            dict: Hospitals and their coordinates.
        """
        hospitals = {}
        for line in f.readlines():
            fields = [values.strip() for values in line.split(",")]
            name = fields[0]
            hospitals[name] = Hospital(
                name=name,
                north_m=int(fields[1]),
                east_m=int(fields[2]),
            )
        return hospitals


# You shouldn't need to modify this class
class Order:
    def __init__(self, time: int, hospital: Hospital, priority: str):
        self.time = time
        self.hospital = hospital
        self.priority = priority
        self.allocated = False
        self.weighted_priority = None

    def __str__(self) -> str:
        return f"[{self.time}] {self.priority}, deliver to {self.hospital.name}"

    @staticmethod
    def load_from_csv(f: TextIO, hospitals: Dict[str, Hospital]) -> List["Order"]:
        """Reads and processes a CSV file object that conforms to the
        orders.csv schema defined in README.md.
        Ok to assume the orders are sorted.

        Args:
            f (file_object): CSV file object to read into a dict.
            hospitals (dict): mapping of hospital name to Hospital objects

        Returns:
            list: Order objects.
        """
        orders = []
        for line in f.readlines():
            fields = [values.strip() for values in line.split(",")]
            orders.append(
                Order(
                    time=int(fields[0]),
                    hospital=hospitals[fields[1]],
                    priority=fields[2],
                )
            )
        return orders


# Feel free to extend as needed
class Flight:
    def __init__(self, launch_time: int, orders: List[Order]):
        self.launch_time = launch_time
        self.orders = orders
        self.distance = Flight.get_distance(orders)

    def __str__(self) -> str:
        orders_str = "->".join([o.hospital.name for o in self.orders])
        return f"<Flight @ {self.launch_time} to {orders_str} returning at {self.get_return_time()}>"

    def get_return_time(self) -> int:
        """
        Get return time in seconds for the flight.
        Returns:
            int: Time (s) that flight is expected to return.
        """
        flight_time_s = round(self.distance / ZIP_SPEED_MPS)
        return self.launch_time + flight_time_s

    @staticmethod
    def get_distance(flight_plan) -> int:
        """
        Given a flight plan, calculate the distance (in meters) to go to each stop and then return to
        the Nest.
        Args:
            flight_plan (List[Orders]): List of orders that make up the flight plan stops, including coordinates.
        Returns:
            int: flight plan distance in meters
        """
        flight_segment_distances = []

        stop_coordinates = [
            {"north_m": order.hospital.north_m, "east_m": order.hospital.east_m}
            for order in flight_plan
        ]

        # add the Nest as the last stop to account for mileage to return home
        stop_coordinates.append({"north_m": NEST[0], "east_m": NEST[1]})

        for index, stop in enumerate(stop_coordinates):
            start_coordinates = (
                [
                    stop_coordinates[index - 1]["north_m"],
                    stop_coordinates[index - 1]["east_m"],
                ]
                if index > 0
                else NEST
            )
            dest_hospital = [stop["north_m"], stop["east_m"]]

            segment_distance = math.dist(start_coordinates, dest_hospital)

            # get the absolute distance of start to end point for the stop
            flight_segment_distances.append(abs(segment_distance))

        flight_path_distance = sum(flight_segment_distances)
        return flight_path_distance

    @staticmethod
    def validate_flight_plan(flight_plan, order) -> bool:
        """
        Validate whether the proposed next stop can be added to the current, valid flight plan.
        Flight plan cannot exceed zip range and must be able to return to the Nest.

        Args:
            flight_plan (List[Orders]): List of Orders currently in the flight plan, already validated.
            order (Order): Order to validate as the next stop in flight plan.
        Returns:
            bool: Whether the flight plan is valid with the passed in proposed next stop.
        """
        print(
            f"Checking if order [{order.time}] {order.hospital.name}--{order.priority} can be added to flight path."
        )

        # add the proposed next stop to the flight plan
        flight_plan.append(order)

        # not rounding distance to avoid over-allocating the zip
        tentative_flight_path_distance = Flight.get_distance(flight_plan)

        print(
            f"Tentative flight plan distance (including return to Nest): "
            + f"{tentative_flight_path_distance} meters/ {ZIP_MAX_CUMULATIVE_RANGE_M} meters max range."
        )
        if tentative_flight_path_distance <= ZIP_MAX_CUMULATIVE_RANGE_M:
            print("Order added!")
            return True
        else:
            print("Could not add order - distance out of range!")
            return False


class ZipScheduler:
    def __init__(
        self,
        hospitals: Dict[str, Hospital],
        num_zips: int,
        max_packages_per_zip: int,
        zip_speed_mps: int,
        zip_max_cumulative_range_m: int,
    ):
        self.hospitals = hospitals
        self.num_zips = num_zips
        self.max_packages_per_zip = max_packages_per_zip
        self.zip_speed_mps = zip_speed_mps
        self.zip_max_cumulative_range_m = zip_max_cumulative_range_m
        self._launched_flights: List[Flight] = []
        # Track which orders haven't been launched yet
        self._unfulfilled_orders: List[Order] = []

    @property
    def unfulfilled_orders(self) -> List[Order]:
        return self._unfulfilled_orders

    def queue_order(self, order: Order) -> None:
        """Add a new order to our queue.

        Note:
            Called every time a new order arrives.

        Args:
            order (Order): the order just placed.
        """
        if order.priority == EMERGENCY:
            order.weighted_priority = 5
        else:
            order.weighted_priority = 1
        self.unfulfilled_orders.append(order)

    def launch_flights(self, current_time: int) -> List[Flight]:
        """Determines which flights should be launched right now.
        Each flight has an ordered list of Orders to serve.

        Note:
            Will be called periodically (approximately once a minute).

        Args:
            current_time (int): Seconds since midnight.

        Returns:
            list: Flight objects that launch at this time.
        """

        # if no orders are queued, there is nothing to do
        if not self._unfulfilled_orders:
            return

        # if we have orders that need to go out, check for any returned zips that we can reuse
        self.track_flights(current_time)

        # sort orders first by priority, then by time they were received
        sorted_orders = sorted(
            self._unfulfilled_orders,
            key=lambda order_item: (-order_item.weighted_priority, order_item.time),
        )

        # logger to show the sorted orders in the console in absence of a UI
        orders_quant = (
            "is 1 unfulfilled order"
            if len(sorted_orders) == 1
            else f"are {len(sorted_orders)} unfulfilled orders"
        )
        print(f"There {orders_quant}.")
        for index, order in enumerate(sorted_orders):
            print(f"Order priority # {index + 1}: {order}, priority: {order.priority}")

        available_zips = self.num_zips - len(self._launched_flights)
        if available_zips:
            zips_quant = (
                "is 1 zip" if available_zips == 1 else f"are {available_zips} zips"
            )
            print(f"There { zips_quant } available.\n")
        else:
            print("No zips available, cannot load.\n\n")
            NUM_MINS_WITH_0_ZIPS_AVAILABLE.append(1)
            if sorted_orders[0].priority == EMERGENCY:
                NUM_MINS_WITH_0_ZIPS_AVAILABLE_AND_EMERGENCY_ORDER.append(1)
            return

        loaded_zips = []

        # iterate through the number of available zips to plan flight paths/allocate orders
        for available_zip in range(available_zips):
            flight_plan = []

            remaining_orders = [
                item for item in sorted_orders if item.allocated is not True
            ]

            # all orders fulfilled
            if not remaining_orders:
                continue

            not_many_remaining_orders = (
                len(remaining_orders) < MIN_RESUPPLY_ORDERS_NEEDED_TO_LOAD
            )
            no_emergency_orders = remaining_orders[0].priority == RESUPPLY
            not_many_zips_available = available_zips < MIN_ZIPS_TO_SHIP_SINGLE_ORDERS

            # this check reduces wait time for Emergency zips
            if (
                not_many_remaining_orders
                and no_emergency_orders
                and not_many_zips_available
            ):
                # We can probably deliver at least 2 non-priority orders at a time,
                # so we can hold off on sending a single order in order to reserve zips for
                # emergency orders
                print(
                    "No emergency orders in queue and mins to ship non-priority orders not met."
                    + "Waiting to collect more orders."
                )
                continue

            # still orders left to ship out
            for order in remaining_orders:
                if len(flight_plan) < MAX_PACKAGES_PER_ZIP:
                    is_valid = Flight.validate_flight_plan(flight_plan.copy(), order)
                    if is_valid:
                        order.allocated = True
                        flight_plan.append(order)
                        print(
                            f"There are currently {len(flight_plan)} orders in this flight plan."
                        )

            if flight_plan:
                # a loaded zip represents a flight that is ready to launch with a finalized flight path
                loaded_zip = Flight(current_time, flight_plan)
                loaded_zips.append(loaded_zip)
                print(f"Flight loaded: {loaded_zip}")

                for loaded_order in flight_plan:
                    order_wait_time = current_time - loaded_order.time

                    # gather stats on the average amount of time an order waited to get loaded
                    if loaded_order.priority == EMERGENCY:
                        EMERGENCY_ORDER_WAIT_TIME.append(order_wait_time)
                    if loaded_order.priority == RESUPPLY:
                        RESUPPLY_ORDER_WAIT_TIME.append(order_wait_time)
                    ORDER_WAIT_TIME.append(order_wait_time)

                    # You should remove any orders from `self.unfilfilled_orders` as you go
                    order_index = self._unfulfilled_orders.index(loaded_order)
                    self._unfulfilled_orders.pop(order_index)

        for flight in loaded_zips:
            # gather flight plan stats
            FLIGHT_PLAN_ORDERS.append(len(flight.orders))
            FLIGHT_PLAN_DISTANCE.append(flight.distance)

        print("All zips packed!")
        self._launched_flights.extend(loaded_zips)
        return loaded_zips

    def track_flights(self, seconds_since_midnight):
        for index, flight in enumerate(self._launched_flights):
            if seconds_since_midnight > flight.get_return_time():
                self._launched_flights.pop(index)
                print(f"{flight} has returned!")


class Runner:
    """A simulation runner that can playback order CSVs as if the day were
    progressing.
    """

    def __init__(self, hospitals_path: str, orders_path: str):
        with open(hospitals_path, "r") as f:
            self.hospitals = Hospital.load_from_csv(f)

        with open(orders_path, "r") as f:
            self.orders = Order.load_from_csv(f, self.hospitals)

        self.scheduler = ZipScheduler(
            hospitals=self.hospitals,
            num_zips=NUM_ZIPS,
            max_packages_per_zip=MAX_PACKAGES_PER_ZIP,
            zip_speed_mps=ZIP_SPEED_MPS,
            zip_max_cumulative_range_m=ZIP_MAX_CUMULATIVE_RANGE_M,
        )
        self.daily_flights_counter = 0

    @staticmethod
    def get_minutes(seconds) -> float:
        """
        Convert to minutes given seconds.
        Args:
            seconds(int): Number of seconds to convert to minutes.
        Returns:
            float: Number of minutes equivalent to the seconds passed in
        """
        minutes = seconds / 60
        return minutes

    def gather_stats(self) -> None:
        """
        Print out daily stats about FLIGHTS and ORDERS at the end of the day.

        Note: You can visualize how the stats change when the algorithm weights change
        by modifying the following variables:
        -NUM_ZIPS
        -MAX_PACKAGES_PER_ZIP
        -ZIP_SPEED_MPS
        -ZIP_MAX_CUMULATIVE_RANGE_M
        -MIN_RESUPPLY_ORDERS_NEEDED_TO_LOAD
        -MIN_ZIPS_TO_SHIP_SINGLE_ORDERS

        The current settings optimize for lowest wait-to-ship times for Emergency orders, within given zip specs.
        """
        print("\n____________________DAILY STATS____________________\n")
        print("ORDER STATS\n")
        # These orders were not launched by midnight
        print(
            f"{len(self.scheduler.unfulfilled_orders)} unfulfilled orders at"
            + " the end of the day"
        )
        avg_order_wait_time = round(
            self.get_minutes(sum(ORDER_WAIT_TIME) / len(ORDER_WAIT_TIME)), 2
        )
        avg_resupply_order_wait_time = round(
            self.get_minutes(
                sum(RESUPPLY_ORDER_WAIT_TIME) / len(RESUPPLY_ORDER_WAIT_TIME)
            ),
            2,
        )
        avg_emergency_order_wait_time = round(
            self.get_minutes(
                sum(EMERGENCY_ORDER_WAIT_TIME) / len(EMERGENCY_ORDER_WAIT_TIME)
            ),
            2,
        )

        print(
            f"The average Emergency order wait time was: {avg_emergency_order_wait_time}"
            + f" minutes for {len(EMERGENCY_ORDER_WAIT_TIME)} Emergency orders served."
        )

        print(
            f"The average Re-Supply wait time was: {avg_resupply_order_wait_time}"
            + f" minutes for {len(RESUPPLY_ORDER_WAIT_TIME)} Re-Supply orders served."
        )

        print(
            f"The average order (Emergency or Re-Supply) wait time was: {avg_order_wait_time}"
            + f" minutes for for {len(ORDER_WAIT_TIME)} total orders served."
        )

        print("\nFLIGHT STATS\n")
        avg_packages_per_flight = round(
            sum(FLIGHT_PLAN_ORDERS) / len(FLIGHT_PLAN_ORDERS), 2
        )
        avg_distance_per_flight = round(
            sum(FLIGHT_PLAN_DISTANCE) / len(FLIGHT_PLAN_DISTANCE)
        )
        percent_max_flight_range_used = round(
            (avg_distance_per_flight / ZIP_MAX_CUMULATIVE_RANGE_M) * 100
        )

        print(f"{self.daily_flights_counter} flights went out today.")
        print(
            f"Flights carried an average of {avg_packages_per_flight} packages and flew and average"
            + f" of {avg_distance_per_flight} meters (max range: {ZIP_MAX_CUMULATIVE_RANGE_M}), using an average"
            + f" {percent_max_flight_range_used}% of the max range."
        )
        print(
            f"There were {len(NUM_MINS_WITH_0_ZIPS_AVAILABLE_AND_EMERGENCY_ORDER)} cumulative minutes with 0 zips"
            + " available and an Emergency package in the queue throughout the day."
        )
        print(
            f"There were {len(NUM_MINS_WITH_0_ZIPS_AVAILABLE)} cumulative minutes with 0 zips available and any package"
            + " in the queue throughout the day."
        )

    def run(self) -> None:
        """Run the simulator.
        This assumes any orders not fulfilled by the end of the day are failed.

        Note:
            This is a barebones implementation that should help get you
            started. You probably want to expand the runner's capabilities.
        """

        # Simulate time going from the first order time, until the end of the
        # day, in 1 minute increments
        sec_per_day = 24 * 60 * 60
        for sec_since_midnight in range(self.orders[0].time, sec_per_day):
            # Find and queue pending orders.
            self.__queue_pending_orders(sec_since_midnight)

            if sec_since_midnight % 60 == 0:
                # Once a minute, poke the flight launcher
                self.__update_launch_flights(sec_since_midnight)

        self.gather_stats()

    def __queue_pending_orders(self, sec_since_midnight: int) -> None:
        """Grab an order from the queue and queue it.

        Args:
            sec_since_midnight (int): Seconds since midnight.
        """
        while self.orders and self.orders[0].time == sec_since_midnight:
            # Find any orders that were placed during this second and tell
            # our scheduler about them
            order = self.orders.pop(0)
            print(
                f"[{sec_since_midnight}] {order.priority} order received",
                f"to {order.hospital.name}",
            )
            self.scheduler.queue_order(order)

    def __update_launch_flights(self, sec_since_midnight: int) -> None:
        """Schedule which flights should launch now.

        Args:
            sec_since_midnight (int): Seconds since midnight.
        """
        flights = self.scheduler.launch_flights(current_time=sec_since_midnight)
        if flights:
            print(f"[{sec_since_midnight}] Scheduling flights:")
            for f in flights:
                print(f"{f}\n")
                self.daily_flights_counter += 1


"""
Usage:

> python3 traveling_zip.py

Runs the provided CSVs
Feel free to edit this if you'd like
"""
if __name__ == "__main__":
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hospitals_path = os.path.join(root_dir, "inputs", "hospitals.csv")
    orders_path = os.path.join(root_dir, "inputs", "orders.csv")
    runner = Runner(
        hospitals_path=hospitals_path,
        orders_path=orders_path,
    )
    runner.run()
