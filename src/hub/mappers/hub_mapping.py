from dataclasses import dataclass
from typing import Optional, Tuple

from hub.models import Hub, HubCategory


@dataclass
class HubMapping:
    hub_category: Optional[HubCategory] = None
    subcategory_hub: Optional[Hub] = None

    def to_tuple(self) -> Tuple[Optional[HubCategory], Optional[Hub]]:
        return (self.hub_category, self.subcategory_hub)
