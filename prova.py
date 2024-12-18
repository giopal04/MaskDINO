#!/usr/bin/env python3

'''
%%
model_specifics = maskdino.maskdino.MaskDINO.from_config(cfg)
metadata = model_specifics['metadata']
classes = metadata.stuff_classes
id2name = {id: cls for id, cls in enumerate(classes)}

#%%
from detectron2.modeling import build_model
model2 = build_model(cfg)

model2.eval()

model2_components = list(model2.children())
comp2 = model2_components[1]
comp2_components = list(comp2.children())
# %%
test = False
if test:
    print(f'{model2 = }')
    print(f'{model2.__dict__ = }')
    print(f'{model2_components = }')
    #print(f'{model2_components.__dict__ = }')
    print(f'{comp2 = }')
    print(f'{comp2.__dict__ = }')
    print(f'{comp2_components = }')
    print(f'{model2.sem_seg_head.predictor.__dict__ = }')
    #print(f'{comp2_components.__dict__ = }')
    for key in model2.keys():
        print(f'{key}: {model2[key]}')

#%%
class DictTensorConverter(nn.Module):
    def __init__(self):
        super().__init__()
        self.keys = None
        pass

    def forward(self, x):
        print(f'{type(x) = }')
        if isinstance(x, dict):
            self.keys = x.keys()
        if 'sem_seg' in self.keys:
            return x['sem_seg']
        else:
            print('Invalid keys')
            for key in self.keys:
                print(key)

# %%
names = ['backbone', 'sem_seg_head', 'criterion']
final_model_v4 = nn.Sequential(OrderedDict((name, component) for name, component in zip(names[:-1], model2_components[:-1])))
# %%
im = torch.from_numpy(cv2.imread(img_path[0]))/255
sz = im.shape
batch = im.permute(2,0,1).view(1,sz[2],sz[0],sz[1]).cuda()
out_new = final_model_v4(batch)
print(len(out_new))
out_dict = out_new[0] # i due elementi della tupla sono un dict e un non type

#%%
for key in out_dict.keys():
    if isinstance(out_dict[key], torch.Tensor):
        print(f'{key}: {out_dict[key].shape}')
    else:
        print(f'{key}: {len(out_dict[key])}')

'''
#%%
from warnings import simplefilter
simplefilter(action='ignore', category=FutureWarning)
simplefilter(action='ignore', category=UserWarning)

import torch, maskdino
from maskdino.config import add_maskdino_config
import numpy as np 
import os, json, cv2, random
#os.environ["CUDA_VISIBLE_DEVICES"] = ""

from detectron2.config import get_cfg
from detectron2.data import MetadataCatalog, DatasetCatalog
from fastai.vision.all import *
# %%

root = '/home/giorgio/venvs/MaskDINO'
root_mnt = '/mnt/shared/MaskDINO_stuff'
img_path = ['/mnt/shared/camvid_old/images/0016E5_08141.png', '/tmp/macchina.jpg']
cfg = get_cfg()
cfg.set_new_allowed(True)
add_maskdino_config(cfg)
cfg.merge_from_file(os.path.join(root,
                                 'MaskDINO/configs/camvid/semantic-segmentation',
                                 'maskdino_R50_bs16_160k_steplr.yaml'))
cfg.MODEL.WEIGHTS = os.path.join(root_mnt,
                                 'MaskDINO_models/downloads',
                                 'maskdino_r50_50ep_100q_celoss_hid1024_3s_semantic_ade20k_48.7miou.pth')

#%%

dataset_dir = os.getenv("DETECTRON2_DATASETS", "/mnt/shared") # defining the root for the dataset

from detectron2.engine import DefaultTrainer
trainer = DefaultTrainer(cfg)
batch_tr = next(trainer.data_loader.__iter__())
for e in batch_tr:
    print(f'{type(e) = }')
    if isinstance(e, dict):
        for i, key in enumerate(e.keys()):
            if i == 0:
                print(f'\t{key} = {e[key]}')
            else:
                print(f'\t{key}')
#trainer.train()

#%%
catalog = DatasetCatalog
camvid_dataset = None
for dataset in catalog.list():
    if 'camvid' and 'train' in dataset:
        camvid_dataset = dataset
#%%
metadata = MetadataCatalog.get(camvid_dataset)
# %%
'''
Prova a fare un train mediante il simple trainer, costruendo tutte le varie componenti una per una
'''
from maskdino.data.dataset_mappers.mask_former_semantic_dataset_mapper import MaskFormerSemanticDatasetMapper
from detectron2.data import build_detection_train_loader
from detectron2.engine.train_loop import SimpleTrainer
from detectron2.modeling import build_model
from detectron2.solver import build_optimizer
import logging
from detectron2.utils.events import EventStorage, get_event_storage
from tqdm import tqdm
import wandb
import weakref

from detectron2.checkpoint import DetectionCheckpointer

from detectron2.utils.memory import retry_if_cuda_oom
from detectron2.modeling.postprocessing import sem_seg_postprocess

from format import Text

class MyTrainer(SimpleTrainer):
    def __init__(self, cfg, log=True, zero_grad_before_forward=False):
        
        model = build_model(cfg)
        mapper = MaskFormerSemanticDatasetMapper(cfg)
        data_loader = build_detection_train_loader(cfg, mapper=mapper)
        optimizer = build_optimizer(cfg, model)

        super().__init__(model, data_loader, optimizer, zero_grad_before_forward=False)
        
        self.log = log
        self.classes = self.get_classes_dict(cfg)

        self.checkpointer = DetectionCheckpointer(
            self.model,
            cfg.OUTPUT_DIR,
            trainer=weakref.proxy(self)
        )
        
        if cfg.MODEL.WEIGHTS is None:
            self.checkpointer.resume_or_load(cfg.MODEL.WEIGHTS, resume=False)
    
    def get_classes_dict(self, cfg):
        metadata = MetadataCatalog.get(cfg.DATASETS.TRAIN[0])
        classes = metadata.get('stuff_classes')

        return {k: cls for k, cls in enumerate(classes)}

    def run_step(self):
        """
        Implement the standard training logic described above.
        """
        assert self.model.training, "[SimpleTrainer] model was changed to eval mode!"
        start = time.perf_counter()
        """
        If you want to do something with the data, you can wrap the dataloader.
        """
        data = next(self._data_loader_iter)

        data_time = time.perf_counter() - start

        if self.zero_grad_before_forward:
            """
            If you need to accumulate gradients or do something similar, you can
            wrap the optimizer with your custom `zero_grad()` method.
            """
            self.optimizer.zero_grad()

        """
        If you want to do something with the losses, you can wrap the model.
        """
        loss_dict, outputs = self.model(data)

        if isinstance(loss_dict, torch.Tensor):
            losses = loss_dict
            loss_dict = {"total_loss": loss_dict}
        else:
            losses = sum(loss_dict.values())
        if not self.zero_grad_before_forward:
            """
            If you need to accumulate gradients or do something similar, you can
            wrap the optimizer with your custom `zero_grad()` method.
            """
            self.optimizer.zero_grad()
    
        if self.log:
            wandb.log({'loss': losses, 'iter': self.iter})
            if self.iter % 100 == 0: #Introduce variable in cfg for images to save 
                self.save_images(data, outputs)
        
        losses.backward()

        self.after_backward()

        if self.async_write_metrics:
            # write metrics asynchronically
            self.concurrent_executor.submit(
                self._write_metrics, loss_dict, data_time, iter=self.iter
            )
        else:
            self._write_metrics(loss_dict, data_time)

        """
        If you need gradient clipping/scaling or other processing, you can
        wrap the optimizer with your custom `step()` method. But it is
        suboptimal as explained in https://arxiv.org/abs/2006.15704 Sec 3.2.4
        """
        self.optimizer.step()
    
    def train(self, start_iter: int = 0, max_iter: int = cfg.SOLVER.MAX_ITER):
        super().train(start_iter, max_iter)

    def before_train(self):
        super().before_train()
        if self.log:
            wandb.init(project='maskdino', config=cfg)

    def after_train(self):
        super().after_train()
        self.checkpointer.save(name=cfg.SAVED_MODEL_NAME)
        if self.log:
            wandb.finish()

    def save_images(self, batched_input: list[dict], outputs: dict) -> None:
        i = random.randint(0, len(batched_input)-1)


        image_dict = batched_input[i]
        image, mask_gt = image_dict['image'], image_dict['sem_seg']

        mask, logits = outputs['pred_masks'][i], outputs['pred_logits'][i]
        mask_cls = F.softmax(logits, dim=-1)[..., :-1]
        mask = mask.sigmoid()
        semseg = torch.einsum("qc,qhw->chw", mask_cls, mask)
        semseg = F.interpolate(semseg.view(1,semseg.shape[0],semseg.shape[1],semseg.shape[2]),
                            size=(image.shape[1], image.shape[2])).detach()
        
        mask_pred = np.argmax(semseg.cpu(), axis=1)

        masked_img = wandb.Image(image, masks={'prediction': {'mask_data': mask_pred[0].numpy(), 'class_labels': self.classes},
                                            'ground_truth': {'mask_data': mask_gt.numpy(), 'class_labels': self.classes}})
        wandb.log({'masked_image': masked_img})

#%%
'''
Inspect the functions/variables (model -> MaskDINO class):
    model.sem_seg_postprocess_before_inference
    sem_seg_postprocess ('ndo sta???)
    model.semantic_inference
    model.semantic_on (deal with instance_on and panoptic_on)

'''
'''
model = build_model(cfg)

mapper = MaskFormerSemanticDatasetMapper(cfg)
data_loader = build_detection_train_loader(cfg, mapper=mapper)

optimizer = build_optimizer(cfg, model)
'''

# the output directory can be set in 
print(cfg.OUTPUT_DIR) # defaults is ./output

#addind a cfg key for the name of the model to save
cfg.SAVED_MODEL_NAME = "final_model" #find better name

new_trainer = MyTrainer(cfg, log=True, zero_grad_before_forward=True)
# %%
#new_trainer.train()

#%%
from detectron2.evaluation.sem_seg_evaluation import SemSegEvaluator

cfg.MODEL.WEIGHTS = os.path.join(root,
                                 'output',
                                 'maskdino_fine_tuned.pth')

model = build_model(cfg)

evaluator = SemSegEvaluator(cfg.DATASETS.TEST[0], cfg.OUTPUT_DIR)
#the path of the images are in:
print(f'{Text(evaluator.input_file_to_gt_file, 'evaluator.input_file_to_gt_file'):inspect}')
# %%