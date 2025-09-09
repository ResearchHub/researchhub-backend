from dataclasses import dataclass
from typing import List, Optional, Tuple

from hub.models import Hub


@dataclass
class HubMapping:
    category_hub: Optional[Hub] = None
    subcategory_hub: Optional[Hub] = None

    def to_tuple(self) -> Tuple[Optional[Hub], Optional[Hub]]:
        return (self.category_hub, self.subcategory_hub)

    def to_list(self) -> List[Hub]:
        hubs = []
        if self.category_hub:
            hubs.append(self.category_hub)
        if self.subcategory_hub:
            hubs.append(self.subcategory_hub)
        return hubs
