import numpy as np
import keras.backend as K
from scipy.misc import imsave, imresize
from scipy.optimize import fmin_l_bfgs_b
from keras.applications import vgg19
from keras.preprocessing.image import load_img, img_to_array
import time
import urllib.request

url = 'https://images-na.ssl-images-amazon.com/images/I/61t8isaMjZL._SX331_BO1,204,203,200_.jpg'  
urllib.request.urlretrieve(url, 'style.jpg')

def preprocess(img_path):
    img = load_img(img_path)
    img = img_to_array(img)
    img = np.rot90(img)
    img = imresize(img, (img_h, img_w, 3)).astype('float64')
    img = np.expand_dims(img, axis=0)
    img = vgg19.preprocess_input(img)

    return img

def deprocess_image(img):
    img = img.reshape((img_h, img_w, 3))

    # subtract mean RGB computed on ImgeNet DB
    img[:, :, 0] += 103.939
    img[:, :, 1] += 116.779
    img[:, :, 2] += 123.68
    img = img[:, :, ::-1]
    img = np.clip(img, 0, 255).astype('float64')
    return img

def content_loss(content, gen):
    return K.sum(K.square(gen - content))

def gram_matrix(x):
    features = K.batch_flatten(K.permute_dimensions(x, (2, 0, 1)))
    gram = K.dot(features, K.transpose(features))
    return gram

def style_loss(style, gen): # find the Euclidean distance between the gram matrices of the feature maps
    S = gram_matrix(style)
    G = gram_matrix(gen)
    channels = 3
    size = img_h * img_w
    return K.sum(K.square(S - G)/(4 * (channels**2) * (size**2)))

def total_variation_loss(x): # to smooth the generated image
    a = K.square(x[:, :img_h - 1, :img_w - 1, :] - x[:, 1:, :img_w - 1, :])
    b = K.square(x[:, :img_h - 1, :img_w - 1, :] - x[:, :img_h - 1, 1:, :])

    return K.sum(K.pow(a+b, 1.25))

CONTENT_IMG_PATH = "content.jpg"
STYLE_IMG_PATH = "style.jpg"

h, w = load_img(CONTENT_IMG_PATH).size
img_h = 400
img_w = int(h*img_h / w)

content_img = K.variable(preprocess(CONTENT_IMG_PATH))
style_img = K.variable(preprocess(STYLE_IMG_PATH))
gen_img = K.placeholder(shape=(1, img_h, img_w, 3))

input_tensor = K.concatenate([content_img, style_img, gen_img], axis=0)

model = vgg19.VGG19(include_top=False, weights='imagenet', input_tensor=input_tensor)
print('Model Loaded...')
print(model.summary())

output_dict = dict([(layer.name, layer.output) for layer in model.layers])

CONTENT_WEIGHT = 1e2
STYLE_WEIGHT = 1e4
TV_WEIGHT = 1e3

loss = 0

# compute content loss
layer_features = output_dict['block2_conv2'] # https://arxiv.org/abs/1603.08155
content_img_features = layer_features[0, :, :, :]
gen_img_features = layer_features[2, :, :, :]
loss += CONTENT_WEIGHT * content_loss(content_img_features, gen_img_features)

# compute style loss
feature_layer_names = ['block1_conv2', 'block2_conv2', 'block3_conv4', 'block4_conv4', 'block5_conv4'] # https://arxiv.org/abs/1603.08155

for name in feature_layer_names:
    layer_features = output_dict[name]
    style_features = layer_features[1, :, :, :]
    gen_img_features = layer_features[2, :, :, :]
    loss += (STYLE_WEIGHT / len(feature_layer_names)) * style_loss(style_features, gen_img_features)

# compute total variation loss
loss += TV_WEIGHT * total_variation_loss(gen_img) # reduce the amount of noise in the generated image

grads = K.gradients(loss, gen_img)
f_output = K.function([gen_img], [loss] + grads) # calculate the loss and the gradients during the optimization

def eval_loss_and_grads(x):
    x = x.reshape((1, img_h, img_w, 3))

    global f_output
    outs = f_output([x])
    loss_value = outs[0]
    if len(outs[1:]) == 1:
        grad_values = outs[1].flatten().astype('float64')
    else:
        grad_values = np.array(outs[1:]).flatten().astype('float64')

    return loss_value, grad_values

class Evaluator:

    def __init__(self):
        self.loss_value = None
        self.grad_value = None

    def loss(self, x):
        assert self.loss_value is None
        self.loss_value, self.grad_value = eval_loss_and_grads(x)
        return self.loss_value

    def grads(self, x):
        assert self.loss_value is not None
        grads_values = np.copy(self.grad_value)
        self.loss_value = None
        self.grad_value = None
        return grads_values

ITER = 100

evaluator = Evaluator()
x = np.random.uniform(0, 255, (1, img_h, img_w, 3)) - 128.

for i in range(ITER):
    start_time = time.time()
    print('step {} ==> '.format(i), end='')
    x, min_val, info = fmin_l_bfgs_b(evaluator.loss, x.flatten(), fprime=evaluator.grads, maxfun=100)
    print('loss: {},'.format(min_val), end='')
    img = deprocess_image(x)
    imsave('generated/generated_img{}.jpg'.format(i), img)
    print(' Image saved. time: {}'.format(time.time() - start_time))

