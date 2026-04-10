# from components import Component, SingleIOComponent, SourceComponent, SinkComponent, DelayComponent, AssertComponent
# from dataclasses import dataclass
# from engine import Engine
# from events import Event
# from utils import ConstantDistribution

# # To transform a DES to a DRS, the passed entities are instead rate updates,
# # and components track their own state and times. 

# @dataclass
# class RateUpdate():
#     type: str
#     rate: float


# class DRS_wrapper():
#     state = RateState(0)

#     def _DRS_arrival_handler(self, engine: Engine, event: Event) -> None:
#         self.state.rate += event.rate
#         super()._default_handle_arrival(engine, event)


# class DRS_Clock(SourceComponent):
#     """
#     DRS_Clock is a component that generates ticks at a constant rate.
#     It is responsible for generating ticks and sending them to the output.

#     In a DRS, the clock must be connected to all other components that need to be timed.
#     """
#     def __init__(self, component_id: str):
#         super().__init__(component_id, "tick", ConstantDistribution(1))
#         self.set_handleable_event("Arrival", self._DRS_arrival_handler)
