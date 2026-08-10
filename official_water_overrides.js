/* Approved Fish Finder Outdoors water-directory corrections.
   Public additions appear before fallback map results.
   Hidden entries suppress known private or closed waters by name and state. */
window.FFO_WATER_OVERRIDES = {
  version: "2026-08-10-named-access-points-v3",
  updated_at: "2026-08-10",
  coverage_note: "Manually reviewed missing-water additions, official access evidence, and private/closed-water corrections.",
  records: [
    {
      name:"Lake Walcott",
      aliases:["lake walcott","walcott lake","lake walcott reservoir"],
      display_name:"Lake Walcott, Lake Walcott State Park, Minidoka County, Idaho",
      lat:42.6747,
      lon:-113.4836,
      state:"Idaho",
      county:"Minidoka",
      category:"water",
      type:"lake",
      official_url:"https://idfg.idaho.gov/ifwis/fishingplanner/water/1133831426835",
      nearby_towns:["rupert","rupert idaho","minidoka county"],
      nearby_town_label:"Rupert",
      public_access_verified:true,
      access_status:"restricted",
      public_access_note:"Idaho Parks and Recreation documents fishing at Lake Walcott State Park, campsites along the water, and day-use boat ramps and docks. Park entrance, camping, seasonal watercraft, or other fees and restrictions may apply; check current park conditions before travel.",
      public_access_source:"Idaho Department of Parks and Recreation — Lake Walcott State Park",
      public_access_source_url:"https://parksandrecreation.idaho.gov/state-park/lake-walcott-state-park/",
      public_access_method:"official-state-park-fishing-access",
      access_points:[
        {
          name:"Lake Walcott State Park",
          access_type:"public-fee",
          verification_status:"agency-verified",
          amenities:["Fishing access","Boat ramps","Docks","Camping","Day-use area"],
          fee_note:"Park entrance, camping, watercraft, or other fees and seasonal restrictions may apply. Check the park before travel.",
          note:"Idaho Parks and Recreation documents fishing, waterside campsites, day-use boat ramps, and docks at the park.",
          operator:"Idaho Department of Parks and Recreation",
          source_name:"Idaho Parks and Recreation — Lake Walcott State Park",
          source_url:"https://parksandrecreation.idaho.gov/state-park/lake-walcott-state-park/",
          last_checked:"2026-08-10"
        }
      ]
    },
    {
      name:"American Falls Reservoir",
      aliases:["american falls reservoir","american falls lake","willow bay reservoir"],
      display_name:"American Falls Reservoir, Power and Bingham Counties, Idaho",
      lat:42.783,
      lon:-112.879,
      state:"Idaho",
      county:"Power / Bingham",
      category:"water",
      type:"reservoir",
      access_points_only:true,
      official_url:"https://idfg.idaho.gov/ifwis/fishingPlanner/water/1127315429370",
      public_access_verified:true,
      access_status:"open",
      public_access_note:"Idaho Fish and Game documents shoreline access through the Fingal, Funk, and Horsch segments of Sterling WMA, plus a boat launch at Sportsman's Park. FFO also lists separately sourced public and private pay-to-use access points below; check each site's current conditions, fees, and posted rules before travel.",
      public_access_source:"Idaho Fish and Game — Sterling WMA",
      public_access_source_url:"https://idfg.idaho.gov/visit/wma/sterling",
      public_access_method:"agency-verified",
      access_points:[
        {
          name:"Seagull Bay Yacht Club",
          access_type:"private-pay",
          verification_status:"operator-verified",
          amenities:["Boat launch","Public pier","Restrooms","Camping","Moorage"],
          fee_note:"The operator states that nonmembers may pay for boat launch/day use and camping. Its posted fee table is dated 2024, so confirm current prices before travel.",
          note:"The operator documents public boat-launch, pier, restroom, camping, and moorage services. This is private property offering pay-to-use public access, not public shoreline.",
          operator:"Seagull Bay Yacht Club",
          source_name:"Seagull Bay Yacht Club — operator website",
          source_url:"https://seagullbayyc.com/",
          operator_url:"https://seagullbayyc.com/fees",
          last_checked:"2026-08-10"
        },
        {
          name:"Willow Bay Recreation Area",
          access_type:"concession",
          verification_status:"agency-verified",
          amenities:["Boat ramp","Public beach","Docks","Camping","Restrooms","Showers","Picnic area"],
          fee_note:"Camping, launch, parking, or other facility fees and restrictions may apply. Confirm current operations before travel.",
          note:"The City of American Falls documents a boat ramp, beaches, docks, camping, restrooms, showers, and other public recreation facilities at Willow Bay.",
          operator:"City of American Falls / site operator",
          source_name:"City of American Falls — Willow Bay Recreation Area",
          source_url:"https://cityofamericanfalls.com/willow-bay-recreation-area/",
          last_checked:"2026-08-10"
        },
        {
          name:"Sportsman's Park",
          access_type:"public-fee",
          verification_status:"agency-verified",
          amenities:["Boat ramp","Day use","Camping","Walking path"],
          fee_note:"Day use, launch, camping, or other fees and restrictions may apply. Confirm current site conditions.",
          note:"Idaho Fish and Game documents a reservoir boat launch at Sportsman's Park; regional visitor information also lists day use, camping, and a walking path.",
          operator:"Local public recreation site",
          source_name:"Idaho Fish and Game — Sterling WMA",
          source_url:"https://idfg.idaho.gov/visit/wma/sterling",
          last_checked:"2026-08-10"
        },
        {
          name:"Sterling WMA — Fingal Segment",
          access_type:"shoreline",
          verification_status:"agency-verified",
          amenities:["Shoreline fishing access","Wildlife management area"],
          fee_note:"Check current WMA rules, seasonal conditions, parking, and posted signs.",
          note:"Idaho Fish and Game identifies the Fingal segment of Sterling WMA as reservoir shoreline access.",
          operator:"Idaho Department of Fish and Game",
          source_name:"Idaho Fish and Game — Sterling WMA",
          source_url:"https://idfg.idaho.gov/visit/wma/sterling",
          last_checked:"2026-08-10"
        },
        {
          name:"Sterling WMA — Funk Segment",
          access_type:"shoreline",
          verification_status:"agency-verified",
          amenities:["Shoreline fishing access","Wildlife management area"],
          fee_note:"Check current WMA rules, seasonal conditions, parking, and posted signs.",
          note:"Idaho Fish and Game identifies the Funk segment of Sterling WMA as reservoir shoreline access.",
          operator:"Idaho Department of Fish and Game",
          source_name:"Idaho Fish and Game — Sterling WMA",
          source_url:"https://idfg.idaho.gov/visit/wma/sterling",
          last_checked:"2026-08-10"
        },
        {
          name:"Sterling WMA — Horsch Segment",
          access_type:"shoreline",
          verification_status:"agency-verified",
          amenities:["Shoreline fishing access","Wildlife management area"],
          fee_note:"Check current WMA rules, seasonal conditions, parking, and posted signs.",
          note:"Idaho Fish and Game identifies the Horsch segment of Sterling WMA as reservoir shoreline access.",
          operator:"Idaho Department of Fish and Game",
          source_name:"Idaho Fish and Game — Sterling WMA",
          source_url:"https://idfg.idaho.gov/visit/wma/sterling",
          last_checked:"2026-08-10"
        },
        {
          name:"American Falls Reservoir West",
          access_type:"boat-ramp",
          verification_status:"official-state-inventory",
          amenities:["Boat ramp","Reservoir access"],
          fee_note:"Confirm current launch, parking, road, and fee conditions before travel.",
          note:"Idaho Fish and Game lists this active named fishing and boating access site in its official access inventory.",
          operator:"Idaho Department of Fish and Game / site partner",
          source_name:"Idaho Fish and Game — Fishing and Boating Access Guide",
          source_url:"https://idfg.idaho.gov/visit/fish-boat-guide",
          lat:42.7804094,
          lon:-112.8814345,
          last_checked:"2026-08-10"
        },
        {
          name:"West Side Boat Ramp",
          access_type:"boat-ramp",
          verification_status:"publisher-documented",
          amenities:["Boat ramp","Parking"],
          fee_note:"Confirm current ownership, road, launch, parking, and fee conditions before travel.",
          note:"Regional destination information identifies a west-side boat ramp at American Falls Reservoir. Use the source and Google listing to confirm the exact entrance before travel.",
          operator:"Operator not confirmed",
          source_name:"Visit Pocatello — American Falls Reservoir",
          source_url:"https://visitpocatello.com/american-falls-reservoir/",
          last_checked:"2026-08-10"
        }
      ]
    }
  ]
};
